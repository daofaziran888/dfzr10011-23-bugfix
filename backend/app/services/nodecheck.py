"""节点状态巡检业务规则：状态流转、字段校验与筛选口径都收在这里。

巡检模块本身不计算均衡阈值，节点巡检负载视图与修复均衡策略状态汇总清单都
只读采集流量均衡模块产出的「均衡执行结果」，保证页面看到的阈值一定来自实际
生效版本；已关闭策略在执行结果里不存在，因此不可能被巡检新数据重新激活。
"""
from __future__ import annotations

from typing import Any

from app.services.balance import BalanceService
from app.store import store

MODULE = "nodecheck"
REQUIRED_FIELDS = ["记录编号", "节点编号", "CPU使用率"]
STATUS_ORDER = ["正常", "亚健康", "异常", "已下线"]
ACTION_RULES = {"标记异常": "亚健康", "隔离节点": "异常", "恢复节点": "已下线"}
NEGATIVE_ACTIONS = []

balance_service = BalanceService()


class NodecheckService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("记录编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return entry, []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"巡检记录 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于节点状态巡检可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return entry, f"巡检记录已{action}"

    # ------------------------------------------------- 修复均衡策略状态汇总清单
    def repair_balance_summary(self) -> list[dict[str, Any]]:
        """巡检模块的修复均衡策略状态汇总清单。

        按既有取数逻辑直接定位 balance 表当前状态，再附带均衡执行结果里的生效
        标记，避免列表页/详情页/巡检页各算各的导致对不上。
        """
        active_keys = {
            (row.get("策略编号"), row.get("策略版本"))
            for row in balance_service.execution_results()
        }
        summary = balance_service.strategy_status_summary()
        for item in summary:
            item["实际生效"] = (item["策略编号"], item["策略版本"]) in active_keys
        return summary

    # --------------------------------------------------------- 节点巡检负载视图
    def node_load_view(self) -> dict[str, Any]:
        """节点巡检负载视图：读取均衡执行结果，只反映实际生效策略。

        返回每个被策略覆盖节点的当前策略版本、唯一生效范围与扩缩容建议；
        视图不保存任何阈值副本，刷新即重新取数，旧阈值无处残留。
        """
        executions = balance_service.execution_results()
        node_view: list[dict[str, Any]] = []
        for row in executions:
            node = row["节点编号"]
            sample = self._latest_sample(node)
            node_view.append({
                "节点编号": node,
                "策略编号": row["策略编号"],
                "策略版本": row["策略版本"],
                "唯一生效范围": row["生效范围"],
                "扩容阈值": row["扩容阈值"],
                "缩容阈值": row["缩容阈值"],
                "权重因子": row["权重因子"],
                "CPU使用率": sample.get("CPU使用率") if sample else None,
                "巡检状态": sample.get("status") if sample else "暂无采样",
                "扩缩容建议": row["扩缩容建议"],
                "冲突处理方式": row["冲突处理方式"],
                "数据来源": row["数据来源"],
            })

        waiting = [
            {
                "策略编号": item["策略编号"],
                "策略版本": item["策略版本"],
                "节点集合": item["节点集合"],
                "等待原因": item["等待原因"],
            }
            for item in self.repair_balance_summary()
            if item.get("等待原因")
        ]
        return {
            "items": node_view,
            "total": len(node_view),
            "waiting_conflicts": waiting,
            "source": "均衡执行结果",
        }

    def _latest_sample(self, node: str) -> dict[str, Any] | None:
        records = [row for row in store.rows(MODULE) if str(row.get("节点编号")) == node]
        return records[-1] if records else None

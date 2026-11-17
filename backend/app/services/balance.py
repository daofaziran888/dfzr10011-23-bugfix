"""采集流量均衡业务规则。

处理链路（修复后）：

1. 策略字段（负载算法、权重因子、扩容阈值、缩容阈值、节点集合等）与策略状态
   在同一次写入里原子保存，杜绝“字段已改、状态仍旧”或反向的半保存问题。
2. 启用策略时做节点集合覆盖冲突校验：同一时刻同一节点集合只允许一个策略生效。
   冲突按策略上登记的处理方式裁决——显式发布优先级或较新版本；失败的一方保持
   原状态，并记录覆盖冲突依据；并发启用最终只保留一个生效结果。
3. 已关闭策略是终态：既不能被再次启用，也不会被巡检侧的新数据重新激活，更不会
   继续参与扩缩容建议。
4. 每次保存/状态流转后立即重算「均衡执行结果」，执行结果只读取实际生效版本的
   阈值，巡检模块与其他业务页面都以这份结果为唯一取数来源，避免旧阈值残留。
"""
from __future__ import annotations

from typing import Any

from app.store import store

MODULE = "balance"

# 可编辑的策略字段：字段与状态必须一起提交保存。
EDITABLE_FIELDS = [
    "负载算法",
    "权重因子",
    "扩容阈值",
    "缩容阈值",
    "最小节点",
    "最大节点",
    "节点集合",
    "优先级",
]
REQUIRED_FIELDS = ["策略编号", "负载算法", "权重因子", "扩容阈值", "缩容阈值", "节点集合"]
STATUS_ORDER = ["草稿", "已生效", "已暂停", "已关闭"]
CLOSED_STATUS = "已关闭"
ACTIVE_STATUS = "已生效"
# 冲突处理路径：显式发布优先级 / 较新策略版本。
RESOLVE_PRIORITY = "显式发布优先级"
RESOLVE_VERSION = "较新策略版本"
RESOLVE_MODES = [RESOLVE_PRIORITY, RESOLVE_VERSION]


def _node_set(entry: dict[str, Any]) -> frozenset[str]:
    """把节点集合字段统一解析成集合，支持「NODE-0001、NODE-0002」等分隔写法。"""
    raw = entry.get("节点集合")
    if isinstance(raw, (list, tuple, set)):
        return frozenset(str(item).strip() for item in raw if str(item).strip())
    text = str(raw or "")
    return frozenset(part.strip() for part in text.replace(",", "、").split("、") if part.strip())


def _version(entry: dict[str, Any]) -> int:
    try:
        return max(int(entry.get("策略版本", 1) or 1), 1)
    except (TypeError, ValueError):
        return 1


def _priority(entry: dict[str, Any]) -> int:
    try:
        return int(entry.get("优先级", 0) or 0)
    except (TypeError, ValueError):
        return 0


class BalanceService:
    # ------------------------------------------------------------------ 查询
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
            rows = [row for row in rows if keyword in str(row.get("策略编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def active_entries(self) -> list[dict[str, Any]]:
        """实际生效（已生效）的策略，按版本号倒序，便于冲突裁决取较新版本。"""
        return sorted(
            (row for row in store.rows(MODULE) if row.get("status") == ACTIVE_STATUS),
            key=lambda row: (_version(row), _priority(row), int(row.get("id", 0))),
            reverse=True,
        )

    # ------------------------------------------------------------------ 写入
    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry: dict[str, Any] = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry["策略编号"] = str(values.get("策略编号")).strip()
        self._apply_fields(entry, values)
        entry["status"] = STATUS_ORDER[0]
        entry["策略状态"] = entry["status"]
        entry["策略版本"] = 1
        entry["冲突处理方式"] = values.get("冲突处理方式") or RESOLVE_VERSION
        entry["停用依据"] = ""
        entry["等待原因"] = ""
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        self._refresh_executions()
        return entry, []

    def update_entry(self, entry_id: int, values: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        """策略字段与状态在同一次调用里原子保存。

        任一字段校验失败都不写入；保存成功后统一刷新执行结果，保证页面刷新后
        列表页、详情页与巡检负载视图看到的是同一份版本数据，不残留旧阈值。
        """
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"均衡策略 {entry_id} 不存在或已归档"
        if entry.get("status") == CLOSED_STATUS:
            return None, "均衡策略已关闭，字段与状态均为终态，不能再修改或重新启用"

        next_status = values.get("status") or entry["status"]
        if next_status not in STATUS_ORDER:
            return None, f"目标状态「{next_status}」不在允许的状态序列里"
        if next_status == ACTIVE_STATUS and entry.get("status") != ACTIVE_STATUS:
            # 走启用冲突裁决，不允许借“保存”绕过覆盖校验。
            return None, "启用操作请走启用策略动作，以便完成节点集合覆盖冲突校验"

        snapshot = dict(entry)
        try:
            self._apply_fields(entry, values)
            entry["status"] = next_status
            entry["策略状态"] = next_status
            entry["pending"] = next_status != CLOSED_STATUS
        except ValueError as exc:
            entry.clear()
            entry.update(snapshot)
            return None, str(exc)

        # 已生效策略的字段修改视为发布新版本，阈值以新版本为实际生效版本。
        if entry["status"] == ACTIVE_STATUS and self._fields_changed(snapshot, entry):
            entry["策略版本"] = _version(snapshot) + 1
        self._refresh_executions()
        return entry, "均衡策略字段与状态已一起保存"

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"均衡策略 {entry_id} 不存在或已归档"
        if action == "启用策略":
            return self._enable(entry)
        if action == "暂停策略":
            if entry.get("status") == CLOSED_STATUS:
                return None, "已关闭策略不能再操作，如需恢复请新建策略版本"
            if entry.get("status") != ACTIVE_STATUS:
                return None, f"当前状态「{entry.get('status')}」不允许暂停策略"
            entry["status"] = "已暂停"
            entry["策略状态"] = entry["status"]
            entry["pending"] = True
            entry["等待原因"] = ""
            self._refresh_executions()
            return entry, "均衡策略已暂停策略"
        if action == "关闭策略":
            if entry.get("status") == CLOSED_STATUS:
                return None, "均衡策略已是关闭状态"
            # 关闭是终态：记录停用依据，执行结果重算后该策略不再参与任何建议，
            # 之后巡检新数据也无法把它重新激活。
            entry["status"] = CLOSED_STATUS
            entry["策略状态"] = CLOSED_STATUS
            entry["pending"] = False
            entry["停用依据"] = f"人工关闭（{entry.get('策略编号')}），关闭后不再参与扩缩容建议"
            entry["等待原因"] = ""
            self._refresh_executions()
            return entry, "均衡策略已关闭策略，停止参与扩缩容建议"
        return None, f"动作「{action}」不属于采集流量均衡可执行范围"

    # ------------------------------------------------------------------ 启用/冲突
    def _enable(self, entry: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        if entry.get("status") == CLOSED_STATUS:
            # 终态保护：关闭后的策略不能被任何路径重新激活。
            return None, "已关闭策略不能重新启用，请基于其配置新建策略版本"
        if entry.get("status") == ACTIVE_STATUS:
            return entry, "均衡策略已处于生效状态"

        target_nodes = _node_set(entry)
        if not target_nodes:
            return None, "节点集合为空，无法启用均衡策略"

        conflicts = [
            other for other in self.active_entries()
            if other["id"] != entry["id"] and _node_set(other) & target_nodes
        ]
        if conflicts:
            winner, reason = self._resolve_conflict(entry, conflicts)
            if winner is not entry:
                # 并发启用只能保留一个结果：失败策略保持原状态，并挂到等待列表。
                entry["等待原因"] = reason
                entry["pending"] = entry["status"] != CLOSED_STATUS
                self._refresh_executions()
                return None, f"启用失败：{reason}，策略保持「{entry['status']}」状态"
            # 当前策略胜出：被覆盖的策略回到已暂停并保留停用依据。
            for loser in conflicts:
                if loser is winner:
                    continue
                loser["status"] = "已暂停"
                loser["策略状态"] = loser["status"]
                loser["pending"] = True
                loser["停用依据"] = reason
                loser["等待原因"] = reason

        entry["status"] = ACTIVE_STATUS
        entry["策略状态"] = ACTIVE_STATUS
        entry["pending"] = False
        entry["等待原因"] = ""
        self._refresh_executions()
        return entry, "均衡策略已启用策略"

    def _resolve_conflict(
        self, challenger: dict[str, Any], conflicts: list[dict[str, Any]]
    ) -> tuple[dict[str, Any], str]:
        """两个覆盖同一节点集合的策略并发启用时的两条裁决路径。"""
        mode = challenger.get("冲突处理方式") or RESOLVE_VERSION
        candidates = [challenger, *conflicts]
        if mode == RESOLVE_PRIORITY:
            winner = max(candidates, key=lambda row: (_priority(row), _version(row), int(row.get("id", 0))))
            reason = (
                f"节点集合覆盖冲突，按显式发布优先级裁决：{winner.get('策略编号')}"
                f"（优先级 {_priority(winner)}）取得唯一生效范围"
            )
            return winner, reason
        # 默认：较新策略版本。
        winner = max(candidates, key=lambda row: (_version(row), _priority(row), int(row.get("id", 0))))
        reason = (
            f"节点集合覆盖冲突，按较新策略版本裁决：{winner.get('策略编号')}"
            f"（版本 v{_version(winner)}）取得唯一生效范围，历史策略保留停用依据"
        )
        return winner, reason

    # ------------------------------------------------------------------ 执行结果
    def execution_results(self) -> list[dict[str, Any]]:
        """均衡执行结果明细：只反映实际生效策略，供巡检模块与其他页面复查。"""
        table = store.rows("balance_execution")
        return [dict(row) for row in table]

    def strategy_status_summary(self) -> list[dict[str, Any]]:
        """修复均衡策略状态汇总清单：状态一律按既有取数逻辑（store 当前值）定位。"""
        summary: list[dict[str, Any]] = []
        for entry in store.rows(MODULE):
            summary.append({
                "id": entry["id"],
                "策略编号": entry.get("策略编号"),
                "策略版本": f"v{_version(entry)}",
                "状态": entry.get("status"),
                "节点集合": sorted(_node_set(entry)),
                "扩容阈值": entry.get("扩容阈值"),
                "缩容阈值": entry.get("缩容阈值"),
                "权重因子": entry.get("权重因子"),
                "冲突处理方式": entry.get("冲突处理方式"),
                "等待原因": entry.get("等待原因", ""),
                "停用依据": entry.get("停用依据", ""),
            })
        return summary

    def _refresh_executions(self) -> None:
        """按实际生效策略重算执行结果，覆盖整张结果表，杜绝旧阈值残留。"""
        table = store.rows("balance_execution")
        table.clear()
        active = self.active_entries()
        result_id = 0
        for entry in active:
            nodes = sorted(_node_set(entry))
            for node in nodes:
                result_id += 1
                table.append({
                    "id": result_id,
                    "节点编号": node,
                    "策略编号": entry.get("策略编号"),
                    "策略版本": f"v{_version(entry)}",
                    "生效范围": "、".join(nodes),
                    "负载算法": entry.get("负载算法"),
                    "权重因子": entry.get("权重因子"),
                    "扩容阈值": entry.get("扩容阈值"),
                    "缩容阈值": entry.get("缩容阈值"),
                    "扩缩容建议": self._suggest(node, entry),
                    "冲突处理方式": entry.get("冲突处理方式"),
                    "数据来源": "均衡执行结果（实际生效版本）",
                })

    def _suggest(self, node: str, entry: dict[str, Any]) -> str:
        """扩缩容建议只读取实际生效策略的阈值；已关闭策略在数据源头就不会进入。"""
        load = self._node_load(node)
        if load is None:
            return "暂无巡检采样，保持当前节点数"
        try:
            scale_out = float(entry.get("扩容阈值"))
            scale_in = float(entry.get("缩容阈值"))
        except (TypeError, ValueError):
            return "阈值未配置完整，不产生建议"
        if load >= scale_out:
            return f"负载 {load:.0f}% 达到扩容阈值 {scale_out:g}%，建议扩容"
        if load <= scale_in:
            return f"负载 {load:.0f}% 低于缩容阈值 {scale_in:g}%，建议缩容"
        return f"负载 {load:.0f}% 位于阈值区间内，维持现状"

    @staticmethod
    def _node_load(node: str) -> float | None:
        """采集流量均衡到节点状态巡检的差异对照：直接读取巡检最新 CPU 采样。"""
        records = [
            row for row in store.rows("nodecheck")
            if str(row.get("节点编号")) == node and row.get("CPU使用率") not in (None, "")
        ]
        if not records:
            return None
        latest = records[-1]
        try:
            return float(latest.get("CPU使用率"))
        except (TypeError, ValueError):
            return None

    # ------------------------------------------------------------------ 工具
    def _apply_fields(self, entry: dict[str, Any], values: dict[str, Any]) -> None:
        for field in EDITABLE_FIELDS:
            if field in values and values[field] is not None:
                entry[field] = str(values[field]).strip()
        if "冲突处理方式" in values and values["冲突处理方式"]:
            mode = str(values["冲突处理方式"]).strip()
            if mode not in RESOLVE_MODES:
                raise ValueError(f"冲突处理方式只支持：{'、'.join(RESOLVE_MODES)}")
            entry["冲突处理方式"] = mode
        entry.setdefault("冲突处理方式", RESOLVE_VERSION)
        for numeric_field in ("权重因子", "扩容阈值", "缩容阈值", "最小节点", "最大节点", "优先级"):
            if numeric_field in entry and entry[numeric_field] != "":
                try:
                    float(entry[numeric_field])
                except ValueError as exc:
                    raise ValueError(f"字段「{numeric_field}」必须是数值，收到：{entry[numeric_field]}") from exc

    @staticmethod
    def _fields_changed(before: dict[str, Any], after: dict[str, Any]) -> bool:
        return any(before.get(field) != after.get(field) for field in EDITABLE_FIELDS)

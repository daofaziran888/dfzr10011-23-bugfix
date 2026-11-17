"""采集流量均衡接口：维护均衡策略，覆盖字段与状态原子保存、启用/暂停/关闭等动作。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.balance import BalanceService

router = APIRouter(prefix="/api/balance", tags=["采集流量均衡"])

service = BalanceService()

LIST_FIELDS = ["策略编号", "负载算法", "权重因子", "最小节点", "最大节点", "扩容阈值", "缩容阈值", "策略状态"]
STATUSES = ["草稿", "已生效", "已暂停", "已关闭"]
# 允许随保存接口一起提交的字段，防止前端把内部字段写进策略。
SAVABLE_KEYS = {
    "负载算法", "权重因子", "扩容阈值", "缩容阈值", "最小节点", "最大节点",
    "节点集合", "优先级", "冲突处理方式", "status",
}


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按策略编号检索"),
    status: str | None = Query(default=None, description="草稿、已生效、已暂停、已关闭"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按策略编号与状态过滤采集流量均衡列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/executions")
def execution_results() -> dict[str, Any]:
    """均衡执行结果明细：只含实际生效策略产出的节点级建议，可直接用于复查。"""
    items = service.execution_results()
    return {"module": "balance", "source": "均衡执行结果", "total": len(items), "items": items}


@router.get("/strategy-summary")
def strategy_summary() -> dict[str, Any]:
    """修复均衡策略状态汇总清单：策略字段与状态以当前保存版本为准。"""
    items = service.strategy_status_summary()
    return {"module": "balance", "total": len(items), "items": items}


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出采集流量均衡清单：返回当前过滤条件下的全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "balance", "total": total, "items": items}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条均衡策略明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"均衡策略 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条均衡策略，缺字段时说明原因而不是静默丢弃。"""
    entry, missing = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="均衡策略已登记", entry=entry)


@router.put("/{entry_id}", response_model=ActionResult)
def update_entry(entry_id: int, payload: EntryPayload) -> ActionResult:
    """策略字段与状态一起保存：任一校验失败整单不写入，成功后立即重算执行结果。"""
    values = {key: value for key, value in payload.values.items() if key in SAVABLE_KEYS}
    entry, message = service.update_entry(entry_id, values)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条均衡策略执行启用策略、暂停策略、关闭策略；不允许的动作会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)

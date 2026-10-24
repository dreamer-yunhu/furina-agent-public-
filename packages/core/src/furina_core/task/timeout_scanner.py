"""审批超时扫描：把到期且仍在等审批的 Task/Execution 成对挂起。

# ── AI-ASSISTED ── 本文件由 AI 生成/改写，待人工复核 ──
# 复核重点：
#   1. **绝不修改 approval_status**。超时只改 Task/Execution，审批保持 PENDING。
#   2. 每条候选分两个 session：先只读校验，再交给 lifecycle_service.transition_pair
#      自带事务迁移。两段之间的窗口就是 ADR 声明的剩余竞态窗口。
#   3. 只有 (APPLIED, APPLIED) 才调用 on_suspended；回调失败不回滚已提交状态。
#   4. 单条失败只计数，不终止整轮。
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Awaitable, Callable

from furina_core.task import lifecycle_service, repository
from furina_core.task.enums import ApprovalStatus, ExecutionStatus, TaskStatus
from furina_core.task.lifecycle import TransitionOutcome
from furina_core.task.models import AgentExecution, AgentTask, ApprovalRequest
from furina_core.task.service import as_utc

logger = logging.getLogger(__name__)

SuspendedHook = Callable[[uuid.UUID, uuid.UUID], Awaitable[None]]

_TERMINAL_TASK = {status.value for status in TaskStatus.terminal()}

_REPORT_FIELDS = (
    "suspended",
    "not_due",
    "already_decided",
    "task_terminal",
    "task_not_waiting",
    "execution_not_waiting",
    "association_mismatch",
    "pair_conflict",
    "deduped",
    "callback_errors",
    "errors",
)


@dataclass
class ScanReport:
    """一轮扫描的统计。字段名与判定分支一一对应，便于断言与排查。"""

    candidates: int = 0
    suspended: int = 0
    not_due: int = 0
    already_decided: int = 0
    task_terminal: int = 0
    task_not_waiting: int = 0
    execution_not_waiting: int = 0
    association_mismatch: int = 0
    pair_conflict: int = 0
    deduped: int = 0
    callback_errors: int = 0
    errors: int = 0

    def record(self, name: str) -> None:
        if name not in _REPORT_FIELDS:
            raise ValueError(f"未登记的扫描结果字段: {name!r}")
        setattr(self, name, getattr(self, name) + 1)

    @property
    def skipped_total(self) -> int:
        return sum(getattr(self, name) for name in _REPORT_FIELDS if name != "suspended")

    @property
    def has_activity(self) -> bool:
        return bool(self.suspended or self.skipped_total)


async def _log_suspended(task_id: uuid.UUID, execution_id: uuid.UUID) -> None:
    """默认钩子：只记日志。**这不是资源释放**。"""
    logger.info("已挂起 task=%s execution=%s", task_id, execution_id)


async def _classify(
    session_factory,
    approval_id: uuid.UUID,
    *,
    now: datetime,
) -> tuple[str, uuid.UUID | None, uuid.UUID | None]:
    """只读校验。返回 `(原因, task_id, execution_id)`；原因不是候选问题时返回跳过原因。"""
    async with session_factory() as session:
        approval = await session.get(ApprovalRequest, approval_id)
        if approval is None:
            return "association_mismatch", None, None
        if approval.approval_status != ApprovalStatus.PENDING.value:
            return "already_decided", None, None
        if as_utc(approval.deadline_at) > now:
            return "not_due", None, None

        execution = await session.get(AgentExecution, approval.execution_id)
        if execution is None or execution.task_id != approval.task_id:
            return "association_mismatch", None, None

        task = await session.get(AgentTask, approval.task_id)
        if task is None:
            return "association_mismatch", None, None
        if task.status in _TERMINAL_TASK:
            return "task_terminal", None, None
        if task.status != TaskStatus.WAITING_APPROVAL.value:
            return "task_not_waiting", None, None
        if execution.status != ExecutionStatus.WAITING_APPROVAL.value:
            return "execution_not_waiting", None, None

        return "candidate", task.id, execution.id


async def _suspend(session_factory, task_id: uuid.UUID, execution_id: uuid.UUID) -> str:
    """成对迁移；返回 `suspended` 或 `pair_conflict`。"""
    async with session_factory() as session:
        task_out, execution_out = await lifecycle_service.transition_pair(
            session,
            task_id=task_id,
            execution_id=execution_id,
            task_from=TaskStatus.WAITING_APPROVAL,
            task_to=TaskStatus.SUSPENDED,
            execution_from=ExecutionStatus.WAITING_APPROVAL,
            execution_to=ExecutionStatus.SUSPENDED,
        )
    if task_out is TransitionOutcome.APPLIED and execution_out is TransitionOutcome.APPLIED:
        return "suspended"
    return "pair_conflict"


async def scan_once(
    session_factory,
    *,
    now: datetime | None = None,
    limit: int = 50,
    on_suspended: SuspendedHook | None = None,
) -> ScanReport:
    """扫描一轮到期审批，返回统计。可独立调用，不依赖后台循环。"""
    now_utc = as_utc(now or datetime.now(UTC))
    hook = on_suspended or _log_suspended
    report = ScanReport()

    async with session_factory() as session:
        due = await repository.list_due_pending_approvals(
            session, now=now_utc, limit=limit
        )
    report.candidates = len(due)

    seen_executions: set[uuid.UUID] = set()
    for approval in due:
        if approval.execution_id in seen_executions:
            report.record("deduped")
            continue
        seen_executions.add(approval.execution_id)

        try:
            reason, task_id, execution_id = await _classify(
                session_factory, approval.id, now=now_utc
            )
            if reason != "candidate":
                report.record(reason)
                continue

            assert task_id is not None and execution_id is not None
            outcome = await _suspend(session_factory, task_id, execution_id)
            report.record(outcome)
            if outcome == "suspended":
                try:
                    await hook(task_id, execution_id)
                except Exception:  # noqa: BLE001 —— 回调失败不回滚已提交状态
                    logger.exception(
                        "on_suspended 回调失败 task=%s execution=%s", task_id, execution_id
                    )
                    report.record("callback_errors")
        except Exception:  # noqa: BLE001 —— 单条失败不终止整轮
            logger.exception("超时扫描处理候选失败 approval=%s", approval.id)
            report.record("errors")

    return report

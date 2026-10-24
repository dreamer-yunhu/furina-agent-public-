"""审批决定服务：持久化决策、幂等重放、冲突识别。

# ── AI-ASSISTED ── 本文件由 AI 生成/改写，待人工复核 ──
# 复核重点：
#   1. 判定顺序不能改：「已有决定」必须在「终态任务」之前。
#      否则任务完成后重放同一个批准会被判成 ILLEGAL_STATE，幂等就破了。
#   2. 只用单行 CAS（repository.decide_approval），不加锁、不加 commit=False。
#   3. 数据库异常原样抛出，不映射成 outcome —— 不能吞掉持久化故障。
#   4. 本服务**不修改 Task/Execution**；恢复校验属于 T22。
#   5. 用户决定只接受 APPROVED / REJECTED；REVOKED 属于取消流程。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from furina_core.task import repository
from furina_core.task.enums import ApprovalStatus, TaskStatus
from furina_core.task.models import AgentTask, ApprovalRequest
from furina_core.task.service import as_utc

_USER_DECISIONS = frozenset({ApprovalStatus.APPROVED, ApprovalStatus.REJECTED})
_TERMINAL_TASK = {status.value for status in TaskStatus.terminal()}


class DecisionOutcome(str, Enum):
    APPLIED = "APPLIED"              # 首次成功写入
    IDEMPOTENT = "IDEMPOTENT"        # 已有相同决定，返回原记录
    CONFLICT = "CONFLICT"            # 已有相反决定
    NOT_FOUND = "NOT_FOUND"          # 审批请求（或所属任务）不存在
    SCOPE_MISMATCH = "SCOPE_MISMATCH"  # 请求与 task/execution 关联不符
    ILLEGAL_STATE = "ILLEGAL_STATE"  # 终态任务，不允许写入决定


@dataclass(frozen=True)
class DecisionResult:
    outcome: DecisionOutcome
    approval: Optional[ApprovalRequest] = None
    late: bool = False


def _is_late(decided_at: datetime | None, deadline_at: datetime | None) -> bool:
    if decided_at is None or deadline_at is None:
        return False
    return as_utc(decided_at) > as_utc(deadline_at)


async def _reload(session: AsyncSession, approval_id: uuid.UUID) -> ApprovalRequest | None:
    """绕过 identity map 取最新行（CAS 失败后必须看别人写了什么）。"""
    return await session.get(ApprovalRequest, approval_id, populate_existing=True)


async def submit_decision(
    session: AsyncSession,
    *,
    approval_id: uuid.UUID,
    task_id: uuid.UUID,
    execution_id: uuid.UUID,
    decision: ApprovalStatus,
    decided_by: str,
    reason: str | None = None,
    now: datetime | None = None,
) -> DecisionResult:
    """提交一次审批决定。

    结果语义见 `DecisionOutcome`；数据库故障以异常形式向上抛出。
    """
    if decision not in _USER_DECISIONS:
        raise ValueError(f"不允许的用户决定: {decision!r}（只接受 APPROVED / REJECTED）")

    now_utc = as_utc(now or datetime.now(UTC))
    assert now_utc is not None  # as_utc 对非 None 必返回 datetime

    approval = await session.get(ApprovalRequest, approval_id)
    if approval is None:
        return DecisionResult(DecisionOutcome.NOT_FOUND)

    if approval.task_id != task_id or approval.execution_id != execution_id:
        return DecisionResult(DecisionOutcome.SCOPE_MISMATCH)

    # ★ 已有决定必须在终态任务校验之前（幂等优先）
    if approval.approval_status != ApprovalStatus.PENDING.value:
        if approval.approval_status == decision.value:
            return DecisionResult(
                DecisionOutcome.IDEMPOTENT,
                approval,
                late=_is_late(approval.decided_at, approval.deadline_at),
            )
        return DecisionResult(
            DecisionOutcome.CONFLICT,
            approval,
            late=_is_late(approval.decided_at, approval.deadline_at),
        )

    task = await session.get(AgentTask, task_id)
    if task is None:
        return DecisionResult(DecisionOutcome.NOT_FOUND)
    if task.status in _TERMINAL_TASK:
        return DecisionResult(
            DecisionOutcome.ILLEGAL_STATE,
            approval,
            late=_is_late(now_utc, approval.deadline_at),
        )

    late = _is_late(now_utc, approval.deadline_at)

    applied = await repository.decide_approval(
        session,
        approval_id=approval_id,
        decision=decision,
        decided_by=decided_by,
        decided_at=now_utc,
        reason=reason,
    )
    if applied:
        latest = await _reload(session, approval_id)
        return DecisionResult(DecisionOutcome.APPLIED, latest, late=late)

    # CAS 未命中 = 并发被抢；重读后按「相同/相反」分类
    latest = await _reload(session, approval_id)
    if latest is None:
        return DecisionResult(DecisionOutcome.NOT_FOUND)
    if latest.approval_status == decision.value:
        return DecisionResult(
            DecisionOutcome.IDEMPOTENT,
            latest,
            late=_is_late(latest.decided_at, latest.deadline_at),
        )
    return DecisionResult(
        DecisionOutcome.CONFLICT,
        latest,
        late=_is_late(latest.decided_at, latest.deadline_at),
    )

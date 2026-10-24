"""恢复前校验与成对恢复（T22）。

# ── AI-ASSISTED ── 本文件由 AI 生成/改写，待人工复核 ──
# 复核重点：
#   1. 只做“校验 + DB 成对迁移”，**不碰 LangGraph、不执行工具**。
#   2. C7 只校验数据库内部一致性；审批行 ↔ checkpoint 的绑定属于 T23，不能声称已做。
#   3. 校验失败一律不改变持久化状态。
#   4. 迟到的批准允许恢复（deadline 不是拒绝条件，C10）。
#   5. 文件校验只读；TOCTOU 窗口由 T14/T23 负责，本服务不宣称消除。
#   6. CAS 冲突（并发被抢）映射为 ILLEGAL_STATE —— ResumeOutcome 没有 CONFLICT，
#      调用方需要区分时应重新读取状态。
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from furina_core.config import settings
from furina_core.sandbox import PathJail, PathOutOfSandbox
from furina_core.task.enums import (
    ApprovalStatus,
    ExecutionStatus,
    TaskStatus,
    ToolExecutionStatus,
    ValidationFailureCode,
)
from furina_core.task.lifecycle import TransitionOutcome
from furina_core.task.lifecycle_service import transition_pair
from furina_core.task.models import AgentExecution, AgentTask, ApprovalRequest
from furina_core.task.service import canonical_args_json, compute_args_hash

_TERMINAL_TASK = {status.value for status in TaskStatus.terminal()}
_TERMINAL_APPROVAL = {
    ApprovalStatus.REJECTED.value,
    ApprovalStatus.REVOKED.value,
}
_RECOVERABLE_STATES = {
    (TaskStatus.WAITING_APPROVAL.value, ExecutionStatus.WAITING_APPROVAL.value),
    (TaskStatus.SUSPENDED.value, ExecutionStatus.SUSPENDED.value),
}
_HEX = set("0123456789abcdef")


class ResumeOutcome(str, Enum):
    RESUMED = "RESUMED"
    NOT_FOUND = "NOT_FOUND"
    SCOPE_MISMATCH = "SCOPE_MISMATCH"
    NOT_APPROVED = "NOT_APPROVED"
    PENDING_APPROVALS = "PENDING_APPROVALS"
    ILLEGAL_STATE = "ILLEGAL_STATE"
    ALREADY_EXECUTED = "ALREADY_EXECUTED"
    OLD_HASH_MISMATCH = "OLD_HASH_MISMATCH"
    ARGS_MISMATCH = "ARGS_MISMATCH"


@dataclass(frozen=True)
class ResumeResult:
    outcome: ResumeOutcome
    failure_code: ValidationFailureCode | None = None
    task: AgentTask | None = None
    execution: AgentExecution | None = None


def _failure(outcome: ResumeOutcome, code: ValidationFailureCode | None = None) -> ResumeResult:
    return ResumeResult(outcome=outcome, failure_code=code)


async def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _read_normalized(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    return text.replace("\r\n", "\n").replace("\r", "\n")


async def _validate_approval_payload(approval: ApprovalRequest) -> bool:
    """C7：数据库内部一致性（不涉及图）。"""
    if not approval.tool_name:
        return False
    if len(approval.args_hash) != 64 or any(ch not in _HEX for ch in approval.args_hash):
        return False
    try:
        payload = json.loads(approval.args_json)
        recomputed = compute_args_hash(payload)
    except (ValueError, TypeError, json.JSONDecodeError):
        return False
    return recomputed == approval.args_hash


async def _validate_target_file(
    approval: ApprovalRequest, jail: PathJail
) -> ResumeOutcome | None:
    """C8：写类工具的目标文件校验。`target_path` 为空表示非写类，跳过。"""
    if approval.target_path is None:
        return None
    try:
        target = jail.resolve(approval.target_path)
    except PathOutOfSandbox:
        return ResumeOutcome.ILLEGAL_STATE

    if approval.old_hash is None:
        # 新文件：审批时不存在。现在存在 = 审批期间被创建
        return ResumeOutcome.OLD_HASH_MISMATCH if target.exists() else None

    if not target.is_file():
        return ResumeOutcome.OLD_HASH_MISMATCH
    current = await _sha256_text(_read_normalized(target))
    if current != approval.old_hash:
        return ResumeOutcome.OLD_HASH_MISMATCH
    return None


async def validate_and_resume(
    session: AsyncSession,
    *,
    task_id: uuid.UUID,
    execution_id: uuid.UUID,
    now: datetime | None = None,
    workspace_root: str | Path | None = None,
) -> ResumeResult:
    """校验并恢复。成功返回 `RESUMED`，失败不改变任何状态。

    `now` 预留给调用方记录/上层策略；**deadline 不是拒绝条件**（C10）。
    """
    _ = now  # 迟到决定允许恢复；当前不参与判断

    task = await session.get(AgentTask, task_id)
    execution = await session.get(AgentExecution, execution_id)
    if task is None or execution is None:
        return _failure(ResumeOutcome.NOT_FOUND, ValidationFailureCode.TASK_INVALID)
    if execution.task_id != task_id:
        return _failure(
            ResumeOutcome.SCOPE_MISMATCH, ValidationFailureCode.APPROVAL_MISMATCH
        )

    state_pair = (task.status, execution.status)
    if state_pair not in _RECOVERABLE_STATES:
        return _failure(ResumeOutcome.ILLEGAL_STATE, ValidationFailureCode.TASK_INVALID)

    approvals = (
        await session.execute(
            select(ApprovalRequest).where(ApprovalRequest.execution_id == execution_id)
        )
    ).scalars().all()
    if not approvals:
        return _failure(ResumeOutcome.NOT_FOUND, ValidationFailureCode.APPROVAL_MISMATCH)

    if any(item.approval_status == ApprovalStatus.PENDING.value for item in approvals):
        return _failure(
            ResumeOutcome.PENDING_APPROVALS, ValidationFailureCode.APPROVAL_MISMATCH
        )
    if any(item.approval_status in _TERMINAL_APPROVAL for item in approvals):
        return _failure(
            ResumeOutcome.NOT_APPROVED, ValidationFailureCode.APPROVAL_MISMATCH
        )
    if any(item.approval_status != ApprovalStatus.APPROVED.value for item in approvals):
        return _failure(
            ResumeOutcome.NOT_APPROVED, ValidationFailureCode.APPROVAL_MISMATCH
        )

    if any(
        item.tool_execution_status != ToolExecutionStatus.NOT_STARTED.value
        for item in approvals
    ):
        return _failure(
            ResumeOutcome.ALREADY_EXECUTED, ValidationFailureCode.ALREADY_EXECUTED
        )

    for item in approvals:
        if not await _validate_approval_payload(item):
            return _failure(
                ResumeOutcome.ARGS_MISMATCH, ValidationFailureCode.ARGS_MISMATCH
            )

    jail = PathJail(workspace_root or settings.sandbox_root)
    for item in approvals:
        outcome = await _validate_target_file(item, jail)
        if outcome is ResumeOutcome.ILLEGAL_STATE:
            return _failure(outcome, ValidationFailureCode.TASK_INVALID)
        if outcome is ResumeOutcome.OLD_HASH_MISMATCH:
            return _failure(outcome, ValidationFailureCode.OLD_HASH_MISMATCH)

    task_from = TaskStatus(task.status)
    execution_from = ExecutionStatus(execution.status)

    # 结束只读事务；transition_pair 需要干净的 Session
    await session.rollback()

    task_out, execution_out = await transition_pair(
        session,
        task_id=task_id,
        execution_id=execution_id,
        task_from=task_from,
        task_to=TaskStatus.RUNNING,
        execution_from=execution_from,
        execution_to=ExecutionStatus.RUNNING,
    )
    if (task_out, execution_out) != (
        TransitionOutcome.APPLIED,
        TransitionOutcome.APPLIED,
    ):
        # CAS 冲突（并发被抢）或状态已变；不改变状态
        return _failure(ResumeOutcome.ILLEGAL_STATE)

    latest_task = await session.get(AgentTask, task_id, populate_existing=True)
    latest_execution = await session.get(
        AgentExecution, execution_id, populate_existing=True
    )
    return ResumeResult(
        outcome=ResumeOutcome.RESUMED,
        task=latest_task,
        execution=latest_execution,
    )

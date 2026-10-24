"""Task / Execution / Approval 的最小数据访问。

本文件只做两件事：

    · 建记录、查记录
    · **条件 UPDATE**（状态迁移的原子性来源）

业务规则（超时怎么算、恢复前校验什么、怎么重委派）不在这里，
在 `service.py` / 各自的 app 里。这样 repository 可以被两边复用，
且不把"什么时候允许迁移"的业务判断埋进 SQL。
"""

# ── AI-ASSISTED ── 本文件由 AI 生成/改写，待人工复核 ──
# 复核重点：
#   1. 所有状态迁移都是 `UPDATE ... WHERE status = :from`，靠 rowcount 判断是否抢到。
#      **不要**改成"先 SELECT 再 UPDATE" —— 那会在并发下失效。
#   2. `create_task` / `create_approval` 不做幂等处理，只负责落库。
#      幂等的 create-or-get 属于阶段 B，届时用 SAVEPOINT + IntegrityError。
#   3. `create_execution` 默认把 graph_thread_id 设为 execution_id。
#      这是本方案的核心约定：一次执行 = 一个 LangGraph 现场。

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Sequence

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from furina_core.task.enums import (
    ApprovalStatus,
    ExecutionStatus,
    TaskStatus,
    ToolExecutionStatus,
)
# <- AI 改动（T19）：repository 承担“配对合法性”的静态校验（Q4=A），
#    业务时机/存在性/归属仍归 Service。
from furina_core.task.lifecycle import (
    is_legal_execution_transition,
    is_legal_task_transition,
)
from furina_core.task.models import AgentExecution, AgentTask, ApprovalRequest


def _now() -> datetime:
    return datetime.now(UTC)


# ----------------------------------------------------------------------
# Task
# ----------------------------------------------------------------------
async def create_task(
    session: AsyncSession,
    *,
    thread_id: uuid.UUID,
    instruction: str,
    parent_task_id: uuid.UUID | None = None,
    redelegation_key: str | None = None,
    status: TaskStatus = TaskStatus.QUEUED,
) -> AgentTask:
    task = AgentTask(
        thread_id=thread_id,
        instruction=instruction,
        parent_task_id=parent_task_id,
        redelegation_key=redelegation_key,
        status=status.value,
    )
    session.add(task)
    await session.commit()
    await session.refresh(task)
    return task


async def get_task(session: AsyncSession, task_id: uuid.UUID) -> AgentTask | None:
    return await session.get(AgentTask, task_id)


async def list_tasks(
    session: AsyncSession,
    *,
    thread_id: uuid.UUID | None = None,
    status: TaskStatus | None = None,
) -> Sequence[AgentTask]:
    stmt = select(AgentTask).order_by(AgentTask.created_at.desc())
    if thread_id is not None:
        stmt = stmt.where(AgentTask.thread_id == thread_id)
    if status is not None:
        stmt = stmt.where(AgentTask.status == status.value)
    return (await session.execute(stmt)).scalars().all()


async def transition_task(
    session: AsyncSession,
    *,
    task_id: uuid.UUID,
    from_status: TaskStatus,
    to_status: TaskStatus,
    failure_reason: str | None = None,
    commit: bool = True,
) -> bool:
    """条件状态迁移。返回 True 表示本次抢到了迁移。

    `commit=False` 供 Service 把 Task/Execution 放进同一个事务（T19 Q3=A）；
    默认 True 保持既有调用行为不变。
    """
    # <- AI 改动（T19）：非法配对直接拒绝，不落库。返回 False 与“条件未命中”同形，
    #    调用方若需要区分原因，应走 lifecycle_service（返回 TransitionOutcome）。
    if not is_legal_task_transition(from_status, to_status):
        return False
    values: dict = {"status": to_status.value, "updated_at": _now()}
    if failure_reason is not None:
        values["failure_reason"] = failure_reason
    result = await session.execute(
        update(AgentTask)
        .where(AgentTask.id == task_id, AgentTask.status == from_status.value)
        .values(**values)
    )
    if commit:
        await session.commit()
    return result.rowcount == 1


# ----------------------------------------------------------------------
# Execution
# ----------------------------------------------------------------------
async def create_execution(
    session: AsyncSession,
    *,
    task_id: uuid.UUID,
    graph_thread_id: str | None = None,
    status: ExecutionStatus = ExecutionStatus.CREATED,
) -> AgentExecution:
    execution_id = uuid.uuid4()
    execution = AgentExecution(
        id=execution_id,
        task_id=task_id,
        # ★ 一次执行 = 一个 LangGraph 现场。默认用 execution_id。
        graph_thread_id=graph_thread_id or str(execution_id),
        status=status.value,
    )
    session.add(execution)
    await session.commit()
    await session.refresh(execution)
    return execution


async def get_execution(
    session: AsyncSession, execution_id: uuid.UUID
) -> AgentExecution | None:
    return await session.get(AgentExecution, execution_id)


async def list_executions(
    session: AsyncSession, *, task_id: uuid.UUID
) -> Sequence[AgentExecution]:
    stmt = (
        select(AgentExecution)
        .where(AgentExecution.task_id == task_id)
        .order_by(AgentExecution.created_at.desc())
    )
    return (await session.execute(stmt)).scalars().all()


async def transition_execution(
    session: AsyncSession,
    *,
    execution_id: uuid.UUID,
    from_status: ExecutionStatus,
    to_status: ExecutionStatus,
    validation_failure_reason: str | None = None,
    finished: bool = False,
    commit: bool = True,
) -> bool:
    """条件状态迁移。`commit=False` 供 Service 组合事务（T19 Q3=A）。"""
    # <- AI 改动（T19）：与 transition_task 同一口径，非法配对直接拒绝。
    if not is_legal_execution_transition(from_status, to_status):
        return False
    values: dict = {"status": to_status.value}
    if validation_failure_reason is not None:
        values["validation_failure_reason"] = validation_failure_reason
    if finished:
        values["finished_at"] = _now()
    result = await session.execute(
        update(AgentExecution)
        .where(
            AgentExecution.id == execution_id,
            AgentExecution.status == from_status.value,
        )
        .values(**values)
    )
    if commit:
        await session.commit()
    return result.rowcount == 1


# ----------------------------------------------------------------------
# Approval
# ----------------------------------------------------------------------
async def create_approval(
    session: AsyncSession,
    *,
    task_id: uuid.UUID,
    execution_id: uuid.UUID,
    tool_call_id: str,
    tool_name: str,
    args_json: str,
    args_hash: str,
    idempotency_key: str,
    deadline_at: datetime,
    target_path: str | None = None,
    old_hash: str | None = None,
) -> ApprovalRequest:
    approval = ApprovalRequest(
        task_id=task_id,
        execution_id=execution_id,
        tool_call_id=tool_call_id,
        tool_name=tool_name,
        args_json=args_json,
        args_hash=args_hash,
        idempotency_key=idempotency_key,
        deadline_at=deadline_at,
        target_path=target_path,
        old_hash=old_hash,
    )
    session.add(approval)
    await session.commit()
    await session.refresh(approval)
    return approval


async def get_approval(
    session: AsyncSession, approval_id: uuid.UUID
) -> ApprovalRequest | None:
    return await session.get(ApprovalRequest, approval_id)


async def list_approvals(
    session: AsyncSession,
    *,
    task_id: uuid.UUID | None = None,
    execution_id: uuid.UUID | None = None,
    approval_status: ApprovalStatus | None = None,
) -> Sequence[ApprovalRequest]:
    stmt = select(ApprovalRequest).order_by(ApprovalRequest.created_at.desc())
    if task_id is not None:
        stmt = stmt.where(ApprovalRequest.task_id == task_id)
    if execution_id is not None:
        stmt = stmt.where(ApprovalRequest.execution_id == execution_id)
    if approval_status is not None:
        stmt = stmt.where(ApprovalRequest.approval_status == approval_status.value)
    return (await session.execute(stmt)).scalars().all()


# ── AI 新增（T21）：到期且仍待审的审批请求 ──
# 复核重点：
#   1. `now` 必须已经过 `as_utc()`；SQLite 下 aware 绑定已实测可用。
#   2. 只读查询，不做任何状态变更；limit<=0 时返回空。
#   3. **必须排除“Task 与 Execution 都已 SUSPENDED”的已挂起对**：
#      超时不改 approval_status，这些审批会永远满足 PENDING+到期；
#      不排除的话，有 limit 的扫描会被它们占满，后面的候选永远轮不到（饥饿）。
#      只排除“两边都 SUSPENDED”的正常完成态，其它不一致仍然返回给 Service 计数。
async def list_due_pending_approvals(
    session: AsyncSession, *, now: datetime, limit: int
) -> Sequence[ApprovalRequest]:
    if limit <= 0:
        return ()
    stmt = (
        select(ApprovalRequest)
        .join(AgentExecution, AgentExecution.id == ApprovalRequest.execution_id)
        .join(AgentTask, AgentTask.id == ApprovalRequest.task_id)
        .where(
            ApprovalRequest.approval_status == ApprovalStatus.PENDING.value,
            ApprovalRequest.deadline_at <= now,
            ~(
                (AgentTask.status == TaskStatus.SUSPENDED.value)
                & (AgentExecution.status == ExecutionStatus.SUSPENDED.value)
            ),
        )
        .order_by(ApprovalRequest.deadline_at.asc(), ApprovalRequest.id.asc())
        .limit(limit)
    )
    return (await session.execute(stmt)).scalars().all()


async def decide_approval(
    session: AsyncSession,
    *,
    approval_id: uuid.UUID,
    decision: ApprovalStatus,
    decided_by: str,
    decided_at: datetime,
    reason: str | None = None,
) -> bool:
    """PENDING → 终态。返回 True 表示本次抢到了决定权。"""
    # 防御：不允许把 PENDING 再写回 PENDING，也不允许调用方传非法值。
    if decision not in (
        ApprovalStatus.APPROVED,
        ApprovalStatus.REJECTED,
        ApprovalStatus.REVOKED,
    ):
        raise ValueError(f"非法的审批决定: {decision!r}")
    result = await session.execute(
        update(ApprovalRequest)
        .where(
            ApprovalRequest.id == approval_id,
            ApprovalRequest.approval_status == ApprovalStatus.PENDING.value,
        )
        .values(
            approval_status=decision.value,
            decided_by=decided_by,
            decided_at=decided_at,
            decision_reason=reason,
            updated_at=_now(),
        )
    )
    await session.commit()
    return result.rowcount == 1


async def claim_tool_execution(
    session: AsyncSession, *, approval_id: uuid.UUID
) -> bool:
    """APPROVED + NOT_STARTED → RUNNING。返回 True 表示本次抢到执行权。"""
    result = await session.execute(
        update(ApprovalRequest)
        .where(
            ApprovalRequest.id == approval_id,
            ApprovalRequest.approval_status == ApprovalStatus.APPROVED.value,
            ApprovalRequest.tool_execution_status
            == ToolExecutionStatus.NOT_STARTED.value,
        )
        .values(
            tool_execution_status=ToolExecutionStatus.RUNNING.value,
            execution_started_at=_now(),
            updated_at=_now(),
        )
    )
    await session.commit()
    return result.rowcount == 1


async def finish_tool_execution(
    session: AsyncSession,
    *,
    approval_id: uuid.UUID,
    status: ToolExecutionStatus,
    result: str | None = None,
    error: str | None = None,
) -> None:
    # 防御：执行结果只能落在三个终态之一；RUNNING/NOT_STARTED 属于认领阶段。
    if status not in (
        ToolExecutionStatus.SUCCEEDED,
        ToolExecutionStatus.FAILED,
        ToolExecutionStatus.UNKNOWN,
    ):
        raise ValueError(f"非法的工具执行终态: {status!r}")
    await session.execute(
        update(ApprovalRequest)
        .where(
            ApprovalRequest.id == approval_id,
            ApprovalRequest.tool_execution_status
            == ToolExecutionStatus.RUNNING.value,
        )
        .values(
            tool_execution_status=status.value,
            execution_finished_at=_now(),
            execution_result=result,
            execution_error=error,
            updated_at=_now(),
        )
    )
    await session.commit()

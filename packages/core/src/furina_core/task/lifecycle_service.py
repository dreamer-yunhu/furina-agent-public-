"""Task / Execution 生命周期服务：时机、存在性、归属、事务编排。

# ── AI-ASSISTED ── 本文件由 AI 生成/改写，待人工复核 ──
# 复核重点：
#   1. 分层：`lifecycle.py` 定“哪对迁移合法”；repository 只做静态校验 + CAS；
#      这里定“现在该不该迁”和“多行怎么一起提交”。
#   2. `transition_pair` 自己开启事务（`session.begin()`），因此调用方**必须**传一个
#      尚未开启事务的 session；已有事务时 SQLAlchemy 会直接报错，而不是静默部分提交。
#   3. 成对迁移宁可全部回滚：任一侧失败，两侧都返回 CONFLICT（表示“未生效”），
#      不返回“另一半 APPLIED”这种会被误解的结果。
#   4. 并发失败一律映射为 CONFLICT（CAS 未抢到）；跨进程/PG 行为未验证。
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from furina_core.task import repository
from furina_core.task.enums import ExecutionStatus, TaskStatus
from furina_core.task.lifecycle import (
    TransitionOutcome,
    is_legal_execution_transition,
    is_legal_task_transition,
)
from furina_core.task.models import AgentExecution, AgentTask

_TERMINAL_TASK = {status.value for status in TaskStatus.terminal()}


class _PairAborted(Exception):
    """内部信号：成对迁移中途失败，需要回滚整个事务。"""


# ----------------------------------------------------------------------
# 单行迁移
# ----------------------------------------------------------------------
async def transition_task(
    session: AsyncSession,
    *,
    task_id: uuid.UUID,
    from_status: TaskStatus,
    to_status: TaskStatus,
    failure_reason: str | None = None,
) -> TransitionOutcome:
    """单条 Task 迁移。判定顺序：存在 → 合法配对 → CAS。"""
    task = await session.get(AgentTask, task_id)
    if task is None:
        return TransitionOutcome.NOT_FOUND
    if not is_legal_task_transition(from_status, to_status):
        return TransitionOutcome.ILLEGAL

    applied = await repository.transition_task(
        session,
        task_id=task_id,
        from_status=from_status,
        to_status=to_status,
        failure_reason=failure_reason,
        commit=True,
    )
    return TransitionOutcome.APPLIED if applied else TransitionOutcome.CONFLICT


async def transition_execution(
    session: AsyncSession,
    *,
    task_id: uuid.UUID,
    execution_id: uuid.UUID,
    from_status: ExecutionStatus,
    to_status: ExecutionStatus,
    validation_failure_reason: str | None = None,
    finished: bool = False,
) -> TransitionOutcome:
    """单条 Execution 迁移。判定顺序：存在 → 归属 → 合法配对 → CAS。"""
    execution = await session.get(AgentExecution, execution_id)
    if execution is None:
        return TransitionOutcome.NOT_FOUND
    if execution.task_id != task_id:
        return TransitionOutcome.SCOPE_MISMATCH
    if not is_legal_execution_transition(from_status, to_status):
        return TransitionOutcome.ILLEGAL

    applied = await repository.transition_execution(
        session,
        execution_id=execution_id,
        from_status=from_status,
        to_status=to_status,
        validation_failure_reason=validation_failure_reason,
        finished=finished,
        commit=True,
    )
    return TransitionOutcome.APPLIED if applied else TransitionOutcome.CONFLICT


# ----------------------------------------------------------------------
# 成对迁移（Task + Execution，同事务）
# ----------------------------------------------------------------------
async def transition_pair(
    session: AsyncSession,
    *,
    task_id: uuid.UUID,
    execution_id: uuid.UUID,
    task_from: TaskStatus,
    task_to: TaskStatus,
    execution_from: ExecutionStatus,
    execution_to: ExecutionStatus,
) -> tuple[TransitionOutcome, TransitionOutcome]:
    """在同一事务里迁移 Task 与 Execution，返回 `(task_outcome, execution_outcome)`。

    约定：
      · 任一侧未生效 → 整个事务回滚，返回 `(CONFLICT, CONFLICT)`
      · `(NOT_FOUND, CONFLICT)` / `(CONFLICT, NOT_FOUND)` 表示对应实体不存在
      · `(CONFLICT, SCOPE_MISMATCH)` 表示 execution 不属于该 task
      · `(ILLEGAL, CONFLICT)` / `(CONFLICT, ILLEGAL)` 表示对应配对不合法
    """
    try:
        async with session.begin():
            task = await session.get(AgentTask, task_id)
            execution = await session.get(AgentExecution, execution_id)

            if task is None:
                return TransitionOutcome.NOT_FOUND, TransitionOutcome.CONFLICT
            if execution is None:
                return TransitionOutcome.CONFLICT, TransitionOutcome.NOT_FOUND
            if execution.task_id != task_id:
                return TransitionOutcome.CONFLICT, TransitionOutcome.SCOPE_MISMATCH
            if not is_legal_task_transition(task_from, task_to):
                return TransitionOutcome.ILLEGAL, TransitionOutcome.CONFLICT
            if not is_legal_execution_transition(execution_from, execution_to):
                return TransitionOutcome.CONFLICT, TransitionOutcome.ILLEGAL

            # 预检现状：避免“先写一半再回滚”的常规路径（并发仍由 CAS 兜底）
            if task.status != task_from.value or execution.status != execution_from.value:
                return TransitionOutcome.CONFLICT, TransitionOutcome.CONFLICT

            task_applied = await repository.transition_task(
                session,
                task_id=task_id,
                from_status=task_from,
                to_status=task_to,
                commit=False,
            )
            execution_applied = await repository.transition_execution(
                session,
                execution_id=execution_id,
                from_status=execution_from,
                to_status=execution_to,
                commit=False,
            )
            if not (task_applied and execution_applied):
                # 预检通过但 CAS 失败 = 并发被抢；抛出以回滚另一侧的写入
                raise _PairAborted
    except _PairAborted:
        return TransitionOutcome.CONFLICT, TransitionOutcome.CONFLICT

    return TransitionOutcome.APPLIED, TransitionOutcome.APPLIED


# ----------------------------------------------------------------------
# Execution 创建入口
# ----------------------------------------------------------------------
async def create_execution_for_task(
    session: AsyncSession,
    *,
    task_id: uuid.UUID,
    graph_thread_id: str | None = None,
) -> tuple[TransitionOutcome, AgentExecution | None]:
    """统一的 Execution 创建入口。

    规则（T19 范围内）：
      · Task 不存在 → NOT_FOUND
      · Task 已在终态 → ILLEGAL（终态任务不再产生新执行）
      · 其余情况创建 CREATED 状态的 Execution

    注意：本函数**不**替调用方决定 Task 是否应先迁移到 RUNNING；
    迁移时机属于调用方（或上层的 claim 流程），这里只保证存在性与终态约束。
    """
    task = await session.get(AgentTask, task_id)
    if task is None:
        return TransitionOutcome.NOT_FOUND, None
    if task.status in _TERMINAL_TASK:
        return TransitionOutcome.ILLEGAL, None

    execution = await repository.create_execution(
        session,
        task_id=task_id,
        graph_thread_id=graph_thread_id,
    )
    return TransitionOutcome.APPLIED, execution

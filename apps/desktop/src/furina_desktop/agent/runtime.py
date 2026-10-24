"""运行时适配层（T23）—— 审批持久化、执行生命周期、图现场定位。

# ── AI-ASSISTED ── 本文件由 AI 生成，待人工复核 ──
# 复核重点：
#   1. 这里只做“运行时编排”，业务规则仍走 T18/T19：
#      `create_or_get_approval` / `transition_pair`，不直接写状态字段。
#   2. 不把 ORM Session 放进 LangGraph state；节点通过模块级 provider 取 runtime。
#   3. `finalize_run` 只处理 RUNNING 对；WAITING_APPROVAL / SUSPENDED 不在这里收尾。
#   4. 单进程假设：按业务线程加 asyncio.Lock。桌面版单实例，多进程不在 T23 范围。
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Mapping

from langchain_core.messages import AIMessage
from langgraph.graph.state import CompiledStateGraph
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from furina_core.config import settings
from furina_core.task import repository
from furina_core.task.decision_service import DecisionOutcome, submit_decision
from furina_core.task.enums import (
    ApprovalStatus,
    ExecutionStatus,
    TaskStatus,
    ToolExecutionStatus,
)
from furina_core.task.lifecycle import TransitionOutcome
from furina_core.task.lifecycle_service import (
    create_execution_for_task,
    suspend_after_resume_failure,
    transition_pair,
)
from furina_core.task.models import AgentExecution, AgentTask, ApprovalRequest
from furina_core.task.resume_service import (
    ResumeOutcome,
    ResumeResult,
    validate_and_resume,
)
from furina_core.task.service import (
    ApprovalConflict,
    compute_args_hash,
    create_or_get_approval,
)

logger = logging.getLogger(__name__)

_ACTIVE_EXECUTION = (
    ExecutionStatus.CREATED.value,
    ExecutionStatus.RUNNING.value,
    ExecutionStatus.WAITING_APPROVAL.value,
    ExecutionStatus.SUSPENDED.value,
)


class ThreadBusy(Exception):
    """同一业务会话已有活动 Execution。"""

    def __init__(self, *, execution_id: uuid.UUID, status: str) -> None:
        self.execution_id = execution_id
        self.status = status
        super().__init__(f"会话已有活动执行：{execution_id} ({status})")


class ApprovalSetupError(Exception):
    """审批落库或状态迁移失败；调用方必须 fail-closed，不得中断送审。"""


class DecisionScopeError(Exception):
    """决定与目标线程/执行不匹配（不存在或越权）。"""


class PreflightError(Exception):
    """恢复前 DB ↔ 图状态核验失败。`code` 用于 HTTP/SSE 映射。"""

    def __init__(self, code: str, detail: dict | None = None) -> None:
        self.code = code
        self.detail = detail or {}
        super().__init__(code)


@dataclass(frozen=True)
class RunContext:
    thread_id: uuid.UUID
    task_id: uuid.UUID
    execution_id: uuid.UUID
    graph_thread_id: str


@dataclass(frozen=True)
class ApprovalDraft:
    """创建审批请求所需的图侧数据。"""

    tool_call_id: str
    tool_name: str
    args: Mapping[str, Any]
    target_path: str | None = None
    old_hash: str | None = None


@dataclass(frozen=True)
class ApprovalHandle:
    approval_id: uuid.UUID
    tool_call_id: str
    args_hash: str
    idempotency_key: str


@dataclass(frozen=True)
class DecisionInput:
    """一条待持久化的决定；`approval_id` 优先，`tool_call_id` 兼容旧前端。"""

    decision: ApprovalStatus
    approval_id: uuid.UUID | None = None
    tool_call_id: str | None = None
    reason: str | None = None


@dataclass(frozen=True)
class DecisionRecord:
    approval_id: uuid.UUID | None
    tool_call_id: str | None
    outcome: DecisionOutcome
    late: bool = False


class AgentRuntime:
    """桌面版运行时适配器：数据库在手，LangGraph 不在核心层。"""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        workspace_root: str | Path | None = None,
        approval_timeout_seconds: int | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.workspace_root = Path(workspace_root or settings.sandbox_root)
        timeout = (
            approval_timeout_seconds
            if approval_timeout_seconds is not None
            else settings.approval_timeout_seconds
        )
        self.approval_timeout_seconds = timeout if timeout > 0 else 3600
        self._thread_locks: dict[uuid.UUID, asyncio.Lock] = {}

    # ------------------------------------------------------------------
    # 执行生命周期
    # ------------------------------------------------------------------
    def _lock(self, thread_id: uuid.UUID) -> asyncio.Lock:
        lock = self._thread_locks.get(thread_id)
        if lock is None:
            lock = asyncio.Lock()
            self._thread_locks[thread_id] = lock
        return lock

    async def start_run(self, *, thread_id: uuid.UUID, instruction: str) -> RunContext:
        """创建 Task + Execution，并返回图现场键。

        `graph_thread_id` 由 `create_execution_for_task` 默认设为 execution_id。
        """
        async with self._lock(thread_id):
            async with self.session_factory() as session:
                active = await self._active_execution(session, thread_id)
                if active is not None:
                    raise ThreadBusy(execution_id=active.id, status=active.status)

                task = await repository.create_task(
                    session,
                    thread_id=thread_id,
                    instruction=instruction,
                )
                moved = await repository.transition_task(
                    session,
                    task_id=task.id,
                    from_status=TaskStatus.QUEUED,
                    to_status=TaskStatus.RUNNING,
                )
                if not moved:
                    await repository.transition_task(
                        session,
                        task_id=task.id,
                        from_status=TaskStatus.QUEUED,
                        to_status=TaskStatus.CANCELLED,
                    )
                    raise ApprovalSetupError("Task 无法迁移到 RUNNING")

                outcome, execution = await create_execution_for_task(
                    session, task_id=task.id
                )
                if outcome is not TransitionOutcome.APPLIED or execution is None:
                    await repository.transition_task(
                        session,
                        task_id=task.id,
                        from_status=TaskStatus.RUNNING,
                        to_status=TaskStatus.FAILED,
                        failure_reason="execution_create_failed",
                    )
                    raise ApprovalSetupError(f"Execution 创建失败：{outcome}")

                moved = await repository.transition_execution(
                    session,
                    execution_id=execution.id,
                    from_status=ExecutionStatus.CREATED,
                    to_status=ExecutionStatus.RUNNING,
                )
                if not moved:
                    # 收尾：不留 CREATED 执行阻塞会话
                    await repository.transition_execution(
                        session,
                        execution_id=execution.id,
                        from_status=ExecutionStatus.CREATED,
                        to_status=ExecutionStatus.CANCELLED,
                    )
                    await repository.transition_task(
                        session,
                        task_id=task.id,
                        from_status=TaskStatus.RUNNING,
                        to_status=TaskStatus.FAILED,
                        failure_reason="execution_start_failed",
                    )
                    raise ApprovalSetupError("Execution 无法迁移到 RUNNING")

                return RunContext(
                    thread_id=thread_id,
                    task_id=task.id,
                    execution_id=execution.id,
                    graph_thread_id=execution.graph_thread_id,
                )

    async def active_execution(self, thread_id: uuid.UUID) -> AgentExecution | None:
        """返回该业务会话当前的活动 Execution（无则 None）。"""
        async with self.session_factory() as session:
            return await self._active_execution(session, thread_id)

    async def _active_execution(
        self, session: AsyncSession, thread_id: uuid.UUID
    ) -> AgentExecution | None:
        stmt = (
            select(AgentExecution)
            .join(AgentTask, AgentTask.id == AgentExecution.task_id)
            .where(
                AgentTask.thread_id == thread_id,
                AgentExecution.status.in_(_ACTIVE_EXECUTION),
            )
            .order_by(AgentExecution.created_at.desc())
            .limit(1)
        )
        return (await session.execute(stmt)).scalars().first()

    # ------------------------------------------------------------------
    # 审批创建（T23-2）
    # ------------------------------------------------------------------
    async def ensure_approvals(
        self,
        *,
        task_id: uuid.UUID,
        execution_id: uuid.UUID,
        drafts: list[ApprovalDraft],
    ) -> dict[str, ApprovalHandle]:
        """幂等创建审批行，并把 Task/Execution 成对迁到 WAITING_APPROVAL。

        返回 `{tool_call_id: ApprovalHandle}`。
        任一步失败抛 `ApprovalSetupError`；调用方不得 `interrupt()`。
        """
        if not drafts:
            return {}

        deadline_at = datetime.now(UTC) + timedelta(
            seconds=self.approval_timeout_seconds
        )
        handles: dict[str, ApprovalHandle] = {}

        try:
            async with self.session_factory() as session:
                task = await session.get(AgentTask, task_id)
                execution = await session.get(AgentExecution, execution_id)
                if task is None or execution is None:
                    raise ApprovalSetupError("Task/Execution 不存在")
                if execution.task_id != task_id:
                    raise ApprovalSetupError("Execution 不属于该 Task")

                pair = (task.status, execution.status)
                if pair not in {
                    (TaskStatus.RUNNING.value, ExecutionStatus.RUNNING.value),
                    (
                        TaskStatus.WAITING_APPROVAL.value,
                        ExecutionStatus.WAITING_APPROVAL.value,
                    ),
                }:
                    raise ApprovalSetupError(f"状态对不允许创建审批：{pair}")

                for draft in drafts:
                    row, _created = await create_or_get_approval(
                        session,
                        task_id=task_id,
                        execution_id=execution_id,
                        tool_call_id=draft.tool_call_id,
                        tool_name=draft.tool_name,
                        args=draft.args,
                        deadline_at=deadline_at,
                        target_path=draft.target_path,
                        old_hash=draft.old_hash,
                    )
                    handles[draft.tool_call_id] = ApprovalHandle(
                        approval_id=row.id,
                        tool_call_id=row.tool_call_id,
                        args_hash=row.args_hash,
                        idempotency_key=row.idempotency_key,
                    )

                if pair == (
                    TaskStatus.RUNNING.value,
                    ExecutionStatus.RUNNING.value,
                ):
                    # create_or_get_approval 末尾的 refresh 会开启新事务；
                    # transition_pair 自己开事务，必须先结束掉只读事务。
                    await session.rollback()
                    task_out, execution_out = await transition_pair(
                        session,
                        task_id=task_id,
                        execution_id=execution_id,
                        task_from=TaskStatus.RUNNING,
                        task_to=TaskStatus.WAITING_APPROVAL,
                        execution_from=ExecutionStatus.RUNNING,
                        execution_to=ExecutionStatus.WAITING_APPROVAL,
                    )
                    if (task_out, execution_out) != (
                        TransitionOutcome.APPLIED,
                        TransitionOutcome.APPLIED,
                    ):
                        raise ApprovalSetupError(
                            "Task/Execution 无法迁移到 WAITING_APPROVAL"
                        )
        except ApprovalConflict as exc:
            raise ApprovalSetupError(f"审批请求冲突：{exc}") from exc
        except ApprovalSetupError:
            raise
        except Exception as exc:  # 数据库故障原样保留链路，但不裸抛给节点
            raise ApprovalSetupError(f"审批落库失败：{exc}") from exc

        return handles

    # ------------------------------------------------------------------
    # 决定持久化（T23-3，调用 T20）
    # ------------------------------------------------------------------
    async def submit_decisions(
        self,
        *,
        thread_id: uuid.UUID,
        execution_id: uuid.UUID,
        decisions: list[DecisionInput],
        decided_by: str,
    ) -> list[DecisionRecord]:
        """逐条调用 T20 持久化决定。

        - `approval_id` 优先；否则按 `tool_call_id` 在当前 Execution 内解析。
        - 不信任客户端传入的 task/execution：一律从审批行反查。
        - 状态机判定完全交给 T20；这里只做归属/存在性校验。
        """
        async with self.session_factory() as session:
            execution = await session.get(AgentExecution, execution_id)
            if execution is None:
                raise DecisionScopeError("执行不存在")
            task = await session.get(AgentTask, execution.task_id)
            if task is None or task.thread_id != thread_id:
                raise DecisionScopeError("执行不属于该会话")

            rows = (
                await session.execute(
                    select(ApprovalRequest).where(
                        ApprovalRequest.execution_id == execution_id
                    )
                )
            ).scalars().all()
            by_id = {row.id: row for row in rows}
            by_call = {row.tool_call_id: row for row in rows}

            results: list[DecisionRecord] = []
            for item in decisions:
                row = None
                if item.approval_id is not None:
                    row = by_id.get(item.approval_id)
                    if row is not None and item.tool_call_id is not None:
                        if row.tool_call_id != item.tool_call_id:
                            results.append(
                                DecisionRecord(
                                    approval_id=item.approval_id,
                                    tool_call_id=item.tool_call_id,
                                    outcome=DecisionOutcome.SCOPE_MISMATCH,
                                )
                            )
                            continue
                elif item.tool_call_id is not None:
                    row = by_call.get(item.tool_call_id)

                if row is None:
                    results.append(
                        DecisionRecord(
                            approval_id=item.approval_id,
                            tool_call_id=item.tool_call_id,
                            outcome=DecisionOutcome.NOT_FOUND,
                        )
                    )
                    continue

                if row.execution_id != execution_id:
                    results.append(
                        DecisionRecord(
                            approval_id=row.id,
                            tool_call_id=row.tool_call_id,
                            outcome=DecisionOutcome.SCOPE_MISMATCH,
                        )
                    )
                    continue

                result = await submit_decision(
                    session,
                    approval_id=row.id,
                    task_id=task.id,
                    execution_id=execution.id,
                    decision=item.decision,
                    decided_by=decided_by,
                    reason=item.reason,
                )
                results.append(
                    DecisionRecord(
                        approval_id=row.id,
                        tool_call_id=row.tool_call_id,
                        outcome=result.outcome,
                        late=result.late,
                    )
                )
            return results

    # ------------------------------------------------------------------
    # 工具执行认领与结束（T23-4，ADR-6）
    # ------------------------------------------------------------------
    async def claim_batch(self, approval_ids: list[uuid.UUID]) -> bool:
        """整批原子认领；任一失败则不执行任何工具。"""
        async with self.session_factory() as session:
            return await repository.claim_tool_executions(
                session, approval_ids=approval_ids
            )

    async def finish_batch(
        self,
        results: dict[uuid.UUID, tuple[ToolExecutionStatus, str | None]],
    ) -> None:
        """逐条写终态。写失败不回滚外部副作用，只记录日志。"""
        async with self.session_factory() as session:
            for approval_id, (status, detail) in results.items():
                try:
                    await repository.finish_tool_execution(
                        session,
                        approval_id=approval_id,
                        status=status,
                        result=detail if status is ToolExecutionStatus.SUCCEEDED else None,
                        error=detail if status is not ToolExecutionStatus.SUCCEEDED else None,
                    )
                except Exception:  # noqa: BLE001 —— 一条失败不能阻止其它条落库
                    logger.exception("工具执行结束记录失败：%s", approval_id)

    # ------------------------------------------------------------------
    # 恢复前置与 T22 校验（T23-4）
    # ------------------------------------------------------------------
    async def preflight_resume(
        self,
        *,
        graph: CompiledStateGraph,
        config: dict,
        thread_id: uuid.UUID,
        execution_id: uuid.UUID,
    ) -> list[uuid.UUID]:
        """双向核验：DB 审批 ↔ 图 interrupts ↔ 工具参数快照。

        返回当前中断批次的 approval_id 列表（T22 的 scope）。
        失败抛 `PreflightError`，**不改变任何数据库状态**。
        """
        try:
            snapshot = await graph.aget_state(config, subgraphs=True)
        except Exception as exc:  # noqa: BLE001 —— 读不到 checkpoint 必须与“不一致”区分
            raise PreflightError(
                "checkpoint_unavailable", {"error": str(exc)}
            ) from exc

        if not snapshot.interrupts:
            raise PreflightError("state_mismatch", {"reason": "graph_not_interrupted"})

        requests: list[dict] = []
        for interrupt_obj in snapshot.interrupts:
            value = interrupt_obj.value if isinstance(interrupt_obj.value, dict) else {}
            requests.extend(value.get("requests", []) or [])
        if not requests:
            raise PreflightError("state_mismatch", {"reason": "interrupt_has_no_requests"})

        ids: list[uuid.UUID] = []
        for request in requests:
            raw = request.get("approval_id")
            if not raw:
                raise PreflightError(
                    "state_mismatch", {"reason": "interrupt_missing_approval_id"}
                )
            try:
                ids.append(uuid.UUID(str(raw)))
            except ValueError as exc:
                raise PreflightError(
                    "state_mismatch", {"reason": f"bad_approval_id:{raw}"}
                ) from exc
        ids = list(dict.fromkeys(ids))

        async with self.session_factory() as session:
            execution = await session.get(AgentExecution, execution_id)
            if execution is None:
                raise PreflightError("not_found", {"reason": "execution_missing"})
            task = await session.get(AgentTask, execution.task_id)
            if task is None or task.thread_id != thread_id:
                raise PreflightError("not_found", {"reason": "execution_not_owned"})
            rows = (
                await session.execute(
                    select(ApprovalRequest).where(
                        ApprovalRequest.execution_id == execution_id,
                        ApprovalRequest.id.in_(ids),
                    )
                )
            ).scalars().all()

        if len(rows) != len(ids):
            raise PreflightError(
                "state_mismatch",
                {
                    "reason": "approval_rows_missing",
                    "requested": [str(i) for i in ids],
                    "found": [str(r.id) for r in rows],
                },
            )

        by_id = {row.id: row for row in rows}
        db_tool_calls = {row.tool_call_id for row in rows}
        interrupt_tool_calls = {str(r.get("tool_call_id")) for r in requests}
        if db_tool_calls != interrupt_tool_calls:
            raise PreflightError(
                "state_mismatch",
                {
                    "reason": "tool_call_ids_differ",
                    "db": sorted(db_tool_calls),
                    "graph": sorted(interrupt_tool_calls),
                },
            )

        # 逐条核对 approval_id ↔ tool_call_id，防止集合相同但配对被交换
        for request in requests:
            approval_id = uuid.UUID(str(request["approval_id"]))
            row = by_id.get(approval_id)
            if row is None or row.tool_call_id != str(request.get("tool_call_id")):
                raise PreflightError(
                    "state_mismatch",
                    {
                        "reason": "approval_tool_call_pair_mismatch",
                        "approval_id": str(approval_id),
                    },
                )

        tool_args: dict[str, Any] = {}
        for snap in _iter_snapshots(snapshot):
            messages = snap.values.get("coder_messages") or []
            for message in messages:
                if not isinstance(message, AIMessage):
                    continue
                for tool_call in message.tool_calls or []:
                    tool_call_id = tool_call.get("id")
                    if tool_call_id:
                        tool_args[tool_call_id] = tool_call.get("args") or {}

        for row in rows:
            args = tool_args.get(row.tool_call_id)
            if args is None:
                raise PreflightError(
                    "state_mismatch",
                    {"reason": f"tool_call_missing:{row.tool_call_id}"},
                )
            if compute_args_hash(args) != row.args_hash:
                raise PreflightError(
                    "args_mismatch", {"tool_call_id": row.tool_call_id}
                )

        return ids

    async def prepare_resume(
        self,
        *,
        graph: CompiledStateGraph,
        config: dict,
        thread_id: uuid.UUID,
        execution_id: uuid.UUID,
        allow_rejected: bool,
    ) -> tuple[ResumeResult, list[uuid.UUID]]:
        """预检 + T22 校验/成对迁移。

        返回 `(T22 结果, 当前批次 approval_id)`；失败时状态不变，调用方不得恢复图。
        批次 id 供恢复失败后的补偿只检查本批。
        """
        approval_ids = await self.preflight_resume(
            graph=graph,
            config=config,
            thread_id=thread_id,
            execution_id=execution_id,
        )

        async with self.session_factory() as session:
            execution = await session.get(AgentExecution, execution_id)
            if execution is None:
                return ResumeResult(outcome=ResumeOutcome.NOT_FOUND), approval_ids
            result = await validate_and_resume(
                session,
                task_id=execution.task_id,
                execution_id=execution_id,
                workspace_root=self.workspace_root,
                approval_ids=approval_ids,
                allow_rejected=allow_rejected,
            )
            return result, approval_ids

    # ------------------------------------------------------------------
    # 运行收尾
    # ------------------------------------------------------------------
    async def handle_resume_failure(
        self,
        execution_id: uuid.UUID,
        *,
        approval_ids: list[uuid.UUID] | None = None,
    ) -> None:
        """图恢复失败的分流（ADR-7）。

        - 本批审批全部 `NOT_STARTED` → `suspend_after_resume_failure`（可重试）
        - 任一已开始/结果未知 → RUNNING→FAILED，禁止自动重放

        `approval_ids` 指定当前批次；`None` 保持旧行为（检查整个 Execution）。
        """
        async with self.session_factory() as session:
            execution = await session.get(AgentExecution, execution_id)
            if execution is None:
                return
            if execution.status != ExecutionStatus.RUNNING.value:
                logger.info(
                    "handle_resume_failure 跳过（execution 状态 %s）", execution.status
                )
                return
            task = await session.get(AgentTask, execution.task_id)
            if task is None or task.status != TaskStatus.RUNNING.value:
                return
            stmt = select(ApprovalRequest).where(
                ApprovalRequest.execution_id == execution_id
            )
            if approval_ids is not None:
                stmt = stmt.where(ApprovalRequest.id.in_(approval_ids))
            approvals = (await session.execute(stmt)).scalars().all()
            started = any(
                item.tool_execution_status
                != ToolExecutionStatus.NOT_STARTED.value
                for item in approvals
            )
            task_id = task.id

        if started:
            await self.finalize_run(
                execution_id,
                status="failed",
                reason="graph_resume_failed_after_tool_started",
            )
            return

        async with self.session_factory() as session:
            task_out, execution_out = await suspend_after_resume_failure(
                session,
                task_id=task_id,
                execution_id=execution_id,
                approval_ids=approval_ids,
            )
        if (task_out, execution_out) != (
            TransitionOutcome.APPLIED,
            TransitionOutcome.APPLIED,
        ):
            await self.finalize_run(
                execution_id,
                status="failed",
                reason="resume_failure_compensation_failed",
            )

    async def finalize_run(
        self, execution_id: uuid.UUID, *, status: str, reason: str | None = None
    ) -> None:
        """图运行结束后的收尾。只处理 RUNNING 对，其它状态不再改。

        `status`: `completed` | `failed` | `interrupted`（interrupted 为 no-op）。
        """
        if status == "interrupted":
            return
        async with self.session_factory() as session:
            execution = await session.get(AgentExecution, execution_id)
            if execution is None:
                logger.warning("finalize_run: execution 不存在 %s", execution_id)
                return
            task = await session.get(AgentTask, execution.task_id)
            if task is None:
                logger.warning("finalize_run: task 不存在 %s", execution.task_id)
                return
            if (
                task.status != TaskStatus.RUNNING.value
                or execution.status != ExecutionStatus.RUNNING.value
            ):
                logger.info(
                    "finalize_run 跳过（状态对 %s/%s）：%s",
                    task.status,
                    execution.status,
                    execution_id,
                )
                return

            # 先取标量，rollback 会让 ORM 实例过期
            task_pk = task.id
            execution_pk = execution.id

            # transition_pair 自己开事务；先把只读事务结束掉
            await session.rollback()

            if status == "completed":
                task_out, execution_out = await transition_pair(
                    session,
                    task_id=task_pk,
                    execution_id=execution_pk,
                    task_from=TaskStatus.RUNNING,
                    task_to=TaskStatus.COMPLETED,
                    execution_from=ExecutionStatus.RUNNING,
                    execution_to=ExecutionStatus.COMPLETED,
                )
            elif status == "failed":
                task_out, execution_out = await transition_pair(
                    session,
                    task_id=task_pk,
                    execution_id=execution_pk,
                    task_from=TaskStatus.RUNNING,
                    task_to=TaskStatus.FAILED,
                    execution_from=ExecutionStatus.RUNNING,
                    execution_to=ExecutionStatus.FAILED,
                )
            else:
                logger.warning("finalize_run: 未知状态 %r", status)
                return

            if (task_out, execution_out) != (
                TransitionOutcome.APPLIED,
                TransitionOutcome.APPLIED,
            ):
                logger.warning(
                    "finalize_run 失败：task=%s execution=%s status=%s outcomes=%s/%s reason=%s",
                    task_pk,
                    execution_pk,
                    status,
                    task_out,
                    execution_out,
                    reason,
                )


def _iter_snapshots(snapshot):
    """深度遍历 StateSnapshot 及其子图（T23-4 取 coder_messages 用）。"""
    yield snapshot
    for task in getattr(snapshot, "tasks", ()) or ():
        child = getattr(task, "state", None)
        if child is not None:
            yield from _iter_snapshots(child)


# ----------------------------------------------------------------------
# 节点侧 provider（不放 state；桌面单进程）
# ----------------------------------------------------------------------
_runtime: AgentRuntime | None = None


def set_runtime(runtime: AgentRuntime | None) -> None:
    global _runtime
    _runtime = runtime


def get_runtime() -> AgentRuntime:
    if _runtime is None:
        raise RuntimeError("AgentRuntime 未初始化：检查 lifespan 是否调用 set_runtime")
    return _runtime

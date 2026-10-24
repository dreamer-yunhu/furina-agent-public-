"""T19 生命周期冒烟测试：迁移矩阵、Repository 校验、Service 编排、事务与并发。

# ── AI-ASSISTED ── 本文件由 AI 生成，待人工复核 ──
# 复核重点：
#   · 第 1–3 段是纯矩阵（穷举 from×to），不碰数据库
#   · 并发段使用**同一进程、两个独立 Session + asyncio.gather**；
#     跨进程与 PostgreSQL 行为未验证
#   · 事务段用失败注入验证“同成同败”，不是只看返回值

跑法（仓库根）：
    .venv-build\\Scripts\\python.exe apps\\desktop\\tests\\smoke_lifecycle.py
"""
from __future__ import annotations

import asyncio
import shutil
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "apps" / "desktop" / "src"))
sys.path.insert(0, str(ROOT / "packages" / "core" / "src"))

from sqlalchemy import event, select  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402
from sqlmodel import SQLModel  # noqa: E402

from furina_core.models import AgentThreadID, User  # noqa: E402
from furina_core.task import repository  # noqa: E402
from furina_core.task import lifecycle_service as lsvc  # noqa: E402
from furina_core.task.enums import ApprovalStatus, ExecutionStatus, TaskStatus  # noqa: E402
from furina_core.task.lifecycle import (  # noqa: E402
    EXECUTION_TRANSITIONS,
    TASK_TRANSITIONS,
    SuspendReason,
    TransitionOutcome,
    allowed_execution_targets,
    allowed_task_targets,
    is_guarded_execution_edge,
    is_guarded_task_edge,
    is_legal_execution_transition,
    is_legal_task_transition,
)
from furina_core.task.models import AgentExecution, AgentTask  # noqa: E402
from furina_desktop.auth import LOCAL_USER_ID  # noqa: E402

PASS, FAIL = "PASS", "FAIL"
_results: list[tuple[str, bool]] = []


def check(label: str, ok: bool, extra: str = "") -> None:
    _results.append((label, ok))
    print(f"  [{PASS if ok else FAIL}] {label}" + (f"   {extra}" if extra else ""))


DB = ROOT / "_smoke_tmp" / "lifecycle" / "t19.sqlite"


def make_factory():
    engine = create_async_engine(f"sqlite+aiosqlite:///{DB.as_posix()}")

    @event.listens_for(engine.sync_engine, "connect")
    def _fk(dbapi_connection, _record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return async_sessionmaker(bind=engine, expire_on_commit=False), engine


async def seed(factory) -> uuid.UUID:
    async with factory() as s:
        s.add(User(id=LOCAL_USER_ID, user_name="local", hashed_password="", personal_preference=None))
        await s.commit()
        thread = AgentThreadID(user_id=LOCAL_USER_ID, title="t19")
        s.add(thread)
        await s.commit()
        await s.refresh(thread)
        return thread.id


async def make_task(factory, thread_id, status: TaskStatus = TaskStatus.QUEUED) -> uuid.UUID:
    async with factory() as s:
        task = await repository.create_task(
            s, thread_id=thread_id, instruction="t19", status=status)
        return task.id


async def make_execution(factory, task_id, status: ExecutionStatus = ExecutionStatus.CREATED) -> uuid.UUID:
    async with factory() as s:
        execution = await repository.create_execution(s, task_id=task_id, status=status)
        return execution.id


async def task_status(factory, task_id) -> str:
    async with factory() as s:
        return (await s.get(AgentTask, task_id)).status


async def execution_status(factory, execution_id) -> str:
    async with factory() as s:
        return (await s.get(AgentExecution, execution_id)).status


# ----------------------------------------------------------------------
# 1–3 纯规则
# ----------------------------------------------------------------------
def matrix_section() -> None:
    print("=== 1. Task 迁移矩阵（穷举 7×7）===")
    mismatches = [
        f"{src.value}->{dst.value}"
        for src in TaskStatus for dst in TaskStatus
        if is_legal_task_transition(src, dst) != (dst in TASK_TRANSITIONS[src])
    ]
    check("all 49 pairs match the table", not mismatches, str(mismatches))
    check("QUEUED->COMPLETED rejected",
          not is_legal_task_transition(TaskStatus.QUEUED, TaskStatus.COMPLETED))
    check("COMPLETED->RUNNING rejected (terminal)",
          not is_legal_task_transition(TaskStatus.COMPLETED, TaskStatus.RUNNING))
    check("RUNNING->QUEUED rejected (no rollback)",
          not is_legal_task_transition(TaskStatus.RUNNING, TaskStatus.QUEUED))
    check("WAITING_APPROVAL->SUSPENDED allowed",
          is_legal_task_transition(TaskStatus.WAITING_APPROVAL, TaskStatus.SUSPENDED))
    check("SUSPENDED->WAITING_APPROVAL rejected",
          not is_legal_task_transition(TaskStatus.SUSPENDED, TaskStatus.WAITING_APPROVAL))
    check("no self transitions",
          not [s for s in TaskStatus if is_legal_task_transition(s, s)])
    check("terminals have no exits",
          not [(s, t) for s in TaskStatus.terminal() for t in allowed_task_targets(s)])
    check("RUNNING->SUSPENDED is legal but guarded",
          is_legal_task_transition(TaskStatus.RUNNING, TaskStatus.SUSPENDED)
          and is_guarded_task_edge(TaskStatus.RUNNING, TaskStatus.SUSPENDED))
    check("Execution RUNNING->SUSPENDED guarded",
          is_legal_execution_transition(ExecutionStatus.RUNNING, ExecutionStatus.SUSPENDED)
          and is_guarded_execution_edge(ExecutionStatus.RUNNING, ExecutionStatus.SUSPENDED))

    print("\n=== 2. Execution 迁移矩阵（穷举 8×8）===")
    mismatches = [
        f"{src.value}->{dst.value}"
        for src in ExecutionStatus for dst in ExecutionStatus
        if is_legal_execution_transition(src, dst) != (dst in EXECUTION_TRANSITIONS[src])
    ]
    check("all 64 pairs match the table", not mismatches, str(mismatches))
    check("CREATED->COMPLETED rejected",
          not is_legal_execution_transition(ExecutionStatus.CREATED, ExecutionStatus.COMPLETED))
    check("VALIDATION_FAILED->RUNNING rejected (terminal)",
          not is_legal_execution_transition(
              ExecutionStatus.VALIDATION_FAILED, ExecutionStatus.RUNNING))
    check("WAITING_APPROVAL->SUSPENDED allowed",
          is_legal_execution_transition(
              ExecutionStatus.WAITING_APPROVAL, ExecutionStatus.SUSPENDED))
    check("SUSPENDED->RUNNING allowed",
          is_legal_execution_transition(ExecutionStatus.SUSPENDED, ExecutionStatus.RUNNING))
    check("no self transitions",
          not [s for s in ExecutionStatus if is_legal_execution_transition(s, s)])
    check("terminals have no exits",
          not [(s, t) for s in ExecutionStatus.terminal() for t in allowed_execution_targets(s)])

    print("\n=== 3. TransitionOutcome 契约 ===")
    expected = {"APPLIED", "ILLEGAL", "CONFLICT", "NOT_FOUND", "SCOPE_MISMATCH"}
    check("outcome values complete", {o.value for o in TransitionOutcome} == expected)


# ----------------------------------------------------------------------
# 4 Repository
# ----------------------------------------------------------------------
async def repository_section(factory, thread_id) -> None:
    print("\n=== 4. Repository：静态合法性 + commit 开关 ===")
    task_id = await make_task(factory, thread_id)

    async with factory() as s:
        applied = await repository.transition_task(
            s, task_id=task_id, from_status=TaskStatus.QUEUED, to_status=TaskStatus.RUNNING)
    check("legal transition applied", applied is True)
    check("state changed", await task_status(factory, task_id) == TaskStatus.RUNNING.value)

    async with factory() as s:
        again = await repository.transition_task(
            s, task_id=task_id, from_status=TaskStatus.QUEUED, to_status=TaskStatus.RUNNING)
    check("stale from returns False", again is False)

    async with factory() as s:
        illegal = await repository.transition_task(
            s, task_id=task_id, from_status=TaskStatus.RUNNING, to_status=TaskStatus.QUEUED)
    check("illegal pair returns False", illegal is False)
    check("illegal pair left state unchanged",
          await task_status(factory, task_id) == TaskStatus.RUNNING.value)

    exec_id = await make_execution(factory, task_id, ExecutionStatus.CREATED)
    async with factory() as s:
        ok = await repository.transition_execution(
            s, execution_id=exec_id, from_status=ExecutionStatus.CREATED,
            to_status=ExecutionStatus.RUNNING)
    check("legal execution transition applied", ok is True)
    async with factory() as s:
        bad = await repository.transition_execution(
            s, execution_id=exec_id, from_status=ExecutionStatus.CREATED,
            to_status=ExecutionStatus.COMPLETED)
    check("illegal execution pair rejected", bad is False)
    check("execution state unchanged",
          await execution_status(factory, exec_id) == ExecutionStatus.RUNNING.value)

    # commit=False + rollback：迁移不生效
    task2 = await make_task(factory, thread_id)
    async with factory() as s:
        applied = await repository.transition_task(
            s, task_id=task2, from_status=TaskStatus.QUEUED,
            to_status=TaskStatus.RUNNING, commit=False)
        check("commit=False returns applied=True", applied is True)
        await s.rollback()
    check("rollback discards the transition",
          await task_status(factory, task2) == TaskStatus.QUEUED.value)


# ----------------------------------------------------------------------
# 5 Service 单行
# ----------------------------------------------------------------------
async def service_single_section(factory, thread_id) -> None:
    print("\n=== 5. Service：单行迁移与结果语义 ===")
    task_id = await make_task(factory, thread_id)

    async with factory() as s:
        out = await lsvc.transition_task(
            s, task_id=task_id, from_status=TaskStatus.QUEUED, to_status=TaskStatus.RUNNING)
    check("APPLIED", out is TransitionOutcome.APPLIED, out.value)

    async with factory() as s:
        out = await lsvc.transition_task(
            s, task_id=task_id, from_status=TaskStatus.QUEUED, to_status=TaskStatus.RUNNING)
    check("CONFLICT on duplicate", out is TransitionOutcome.CONFLICT, out.value)

    async with factory() as s:
        out = await lsvc.transition_task(
            s, task_id=task_id, from_status=TaskStatus.RUNNING, to_status=TaskStatus.QUEUED)
    check("ILLEGAL on forbidden pair", out is TransitionOutcome.ILLEGAL, out.value)

    async with factory() as s:
        out = await lsvc.transition_task(
            s, task_id=uuid.uuid4(), from_status=TaskStatus.QUEUED,
            to_status=TaskStatus.RUNNING)
    check("NOT_FOUND on missing task", out is TransitionOutcome.NOT_FOUND, out.value)

    exec_id = await make_execution(factory, task_id, ExecutionStatus.CREATED)
    async with factory() as s:
        out = await lsvc.transition_execution(
            s, task_id=task_id, execution_id=exec_id,
            from_status=ExecutionStatus.CREATED, to_status=ExecutionStatus.RUNNING)
    check("execution APPLIED", out is TransitionOutcome.APPLIED, out.value)

    async with factory() as s:
        out = await lsvc.transition_execution(
            s, task_id=task_id, execution_id=exec_id,
            from_status=ExecutionStatus.CREATED, to_status=ExecutionStatus.RUNNING)
    check("execution CONFLICT on duplicate", out is TransitionOutcome.CONFLICT, out.value)

    async with factory() as s:
        out = await lsvc.transition_execution(
            s, task_id=task_id, execution_id=exec_id,
            from_status=ExecutionStatus.RUNNING, to_status=ExecutionStatus.CREATED)
    check("execution ILLEGAL on forbidden pair", out is TransitionOutcome.ILLEGAL, out.value)

    async with factory() as s:
        out = await lsvc.transition_execution(
            s, task_id=uuid.uuid4(), execution_id=exec_id,
            from_status=ExecutionStatus.RUNNING, to_status=ExecutionStatus.COMPLETED)
    check("SCOPE_MISMATCH when task differs", out is TransitionOutcome.SCOPE_MISMATCH, out.value)

    async with factory() as s:
        out = await lsvc.transition_execution(
            s, task_id=task_id, execution_id=uuid.uuid4(),
            from_status=ExecutionStatus.RUNNING, to_status=ExecutionStatus.COMPLETED)
    check("execution NOT_FOUND", out is TransitionOutcome.NOT_FOUND, out.value)


# ----------------------------------------------------------------------
# 6 成对迁移
# ----------------------------------------------------------------------
async def pair_section(factory, thread_id) -> None:
    print("\n=== 6. 成对迁移：同成同败 ===")
    task_id = await make_task(factory, thread_id, TaskStatus.RUNNING)
    exec_id = await make_execution(factory, task_id, ExecutionStatus.RUNNING)

    async with factory() as s:
        out = await lsvc.transition_pair(
            s, task_id=task_id, execution_id=exec_id,
            task_from=TaskStatus.RUNNING, task_to=TaskStatus.WAITING_APPROVAL,
            execution_from=ExecutionStatus.RUNNING,
            execution_to=ExecutionStatus.WAITING_APPROVAL)
    check("pair APPLIED both",
          out == (TransitionOutcome.APPLIED, TransitionOutcome.APPLIED), str(out))
    check("task moved",
          await task_status(factory, task_id) == TaskStatus.WAITING_APPROVAL.value)
    check("execution moved",
          await execution_status(factory, exec_id) == ExecutionStatus.WAITING_APPROVAL.value)

    # 执行侧 from 不匹配 → 两侧都不动
    task2 = await make_task(factory, thread_id, TaskStatus.RUNNING)
    exec2 = await make_execution(factory, task2, ExecutionStatus.RUNNING)
    async with factory() as s:
        out = await lsvc.transition_pair(
            s, task_id=task2, execution_id=exec2,
            task_from=TaskStatus.RUNNING, task_to=TaskStatus.WAITING_APPROVAL,
            execution_from=ExecutionStatus.CREATED,
            execution_to=ExecutionStatus.RUNNING)
    check("pair CONFLICT both", out == (TransitionOutcome.CONFLICT, TransitionOutcome.CONFLICT),
          str(out))
    check("task untouched after pair conflict",
          await task_status(factory, task2) == TaskStatus.RUNNING.value)

    # 任务侧配对非法
    task3 = await make_task(factory, thread_id, TaskStatus.RUNNING)
    exec3 = await make_execution(factory, task3, ExecutionStatus.RUNNING)
    async with factory() as s:
        out = await lsvc.transition_pair(
            s, task_id=task3, execution_id=exec3,
            task_from=TaskStatus.RUNNING, task_to=TaskStatus.QUEUED,
            execution_from=ExecutionStatus.RUNNING, execution_to=ExecutionStatus.COMPLETED)
    check("pair reports task ILLEGAL", out == (TransitionOutcome.ILLEGAL, TransitionOutcome.CONFLICT),
          str(out))
    check("nothing moved on illegal pair",
          await task_status(factory, task3) == TaskStatus.RUNNING.value
          and await execution_status(factory, exec3) == ExecutionStatus.RUNNING.value)

    # 失败注入：任务已写、执行侧返回 False → 整个事务回滚
    task4 = await make_task(factory, thread_id, TaskStatus.RUNNING)
    exec4 = await make_execution(factory, task4, ExecutionStatus.RUNNING)
    original = lsvc.repository.transition_execution

    async def _fail(*args, **kwargs):
        return False

    lsvc.repository.transition_execution = _fail
    try:
        async with factory() as s:
            out = await lsvc.transition_pair(
                s, task_id=task4, execution_id=exec4,
                task_from=TaskStatus.RUNNING, task_to=TaskStatus.WAITING_APPROVAL,
                execution_from=ExecutionStatus.RUNNING,
                execution_to=ExecutionStatus.WAITING_APPROVAL)
            check("pair aborts as CONFLICT", out == (TransitionOutcome.CONFLICT, TransitionOutcome.CONFLICT),
                  str(out))
            check("session usable after abort",
                  (await s.get(AgentTask, task4)) is not None)
    finally:
        lsvc.repository.transition_execution = original
    check("first write rolled back",
          await task_status(factory, task4) == TaskStatus.RUNNING.value)
    check("execution untouched",
          await execution_status(factory, exec4) == ExecutionStatus.RUNNING.value)


# ----------------------------------------------------------------------
# 7 创建入口
# ----------------------------------------------------------------------
async def create_execution_section(factory, thread_id) -> None:
    print("\n=== 7. Execution 创建入口 ===")
    async with factory() as s:
        out, created = await lsvc.create_execution_for_task(s, task_id=uuid.uuid4())
    check("NOT_FOUND for missing task", out is TransitionOutcome.NOT_FOUND and created is None)

    terminal_task = await make_task(factory, thread_id, TaskStatus.COMPLETED)
    async with factory() as s:
        out, created = await lsvc.create_execution_for_task(s, task_id=terminal_task)
    check("ILLEGAL for terminal task", out is TransitionOutcome.ILLEGAL and created is None)

    live_task = await make_task(factory, thread_id, TaskStatus.RUNNING)
    async with factory() as s:
        out, created = await lsvc.create_execution_for_task(s, task_id=live_task)
    check("APPLIED for live task", out is TransitionOutcome.APPLIED and created is not None)
    check("created in CREATED state",
          created is not None and created.status == ExecutionStatus.CREATED.value)
    check("graph_thread_id equals execution id",
          created is not None and created.graph_thread_id == str(created.id))


# ----------------------------------------------------------------------
# 8 并发（同进程、两个独立 Session）
# ----------------------------------------------------------------------
async def concurrency_section(factory, thread_id) -> None:
    print("\n=== 8. 并发：两个独立 Session 抢同一次迁移 ===")
    task_id = await make_task(factory, thread_id, TaskStatus.RUNNING)
    gate = asyncio.Event()

    async def worker():
        async with factory() as s:
            await gate.wait()
            try:
                return await lsvc.transition_task(
                    s, task_id=task_id, from_status=TaskStatus.RUNNING,
                    to_status=TaskStatus.COMPLETED)
            except Exception as exc:  # noqa: BLE001
                return f"{type(exc).__name__}: {str(exc)[:40]}"

    async def opener():
        await asyncio.sleep(0.05)
        gate.set()

    results = await asyncio.gather(worker(), worker(), opener())
    print("   ", results[0], results[1])
    outcomes = [r for r in results[:2] if isinstance(r, TransitionOutcome)]
    check("no database-locked surprises", len(outcomes) == 2, str(results[:2]))
    check("exactly one APPLIED",
          outcomes.count(TransitionOutcome.APPLIED) == 1,
          str([o.value for o in outcomes]))
    check("the other CONFLICT",
          outcomes.count(TransitionOutcome.CONFLICT) == 1,
          str([o.value for o in outcomes]))
    check("final state COMPLETED",
          await task_status(factory, task_id) == TaskStatus.COMPLETED.value)


# ----------------------------------------------------------------------
# 9 T19 变更：受保护的 RUNNING→SUSPENDED
# ----------------------------------------------------------------------
async def guarded_section(factory, thread_id) -> None:
    print("\n=== 9. T19 变更：受保护的 RUNNING→SUSPENDED ===")

    async def make_running(*, started: bool = False):
        task_id = await make_task(factory, thread_id, TaskStatus.RUNNING)
        exec_id = await make_execution(factory, task_id, ExecutionStatus.RUNNING)
        async with factory() as s:
            approval = await repository.create_approval(
                s, task_id=task_id, execution_id=exec_id,
                tool_call_id=f"c-{uuid.uuid4().hex[:6]}",
                tool_name="write_file_tool", args_json="{}", args_hash="a" * 64,
                idempotency_key=uuid.uuid4().hex * 2,
                deadline_at=datetime.now(UTC) + timedelta(minutes=5),
            )
        async with factory() as s:
            await repository.decide_approval(
                s, approval_id=approval.id, decision=ApprovalStatus.APPROVED,
                decided_by="local", decided_at=datetime.now(UTC))
        if started:
            async with factory() as s:
                await repository.claim_tool_execution(s, approval_id=approval.id)
        return task_id, exec_id, approval.id

    t, e, _ = await make_running()
    async with factory() as s:
        generic = await repository.transition_task(
            s, task_id=t, from_status=TaskStatus.RUNNING,
            to_status=TaskStatus.SUSPENDED)
    check("repository rejects guarded edge by default", generic is False)
    check("state unchanged", await task_status(factory, t) == TaskStatus.RUNNING.value)

    async with factory() as s:
        allowed = await repository.transition_task(
            s, task_id=t, from_status=TaskStatus.RUNNING,
            to_status=TaskStatus.SUSPENDED, guarded_ok=True)
    check("repository allows with guarded_ok", allowed is True)

    t, e, _ = await make_running()
    async with factory() as s:
        out = await lsvc.transition_task(
            s, task_id=t, from_status=TaskStatus.RUNNING, to_status=TaskStatus.SUSPENDED)
    check("service single entry returns ILLEGAL", out is TransitionOutcome.ILLEGAL, out.value)

    t, e, _ = await make_running()
    async with factory() as s:
        pair = await lsvc.transition_pair(
            s, task_id=t, execution_id=e,
            task_from=TaskStatus.RUNNING, task_to=TaskStatus.SUSPENDED,
            execution_from=ExecutionStatus.RUNNING, execution_to=ExecutionStatus.SUSPENDED)
    check("transition_pair rejects without guarded_ok",
          pair == (TransitionOutcome.ILLEGAL, TransitionOutcome.CONFLICT), str(pair))
    check("nothing moved",
          (await task_status(factory, t), await execution_status(factory, e))
          == (TaskStatus.RUNNING.value, ExecutionStatus.RUNNING.value))

    t, e, _ = await make_running()
    async with factory() as s:
        out = await lsvc.suspend_after_resume_failure(
            s, task_id=t, execution_id=e)
    check("dedicated entry APPLIED",
          out == (TransitionOutcome.APPLIED, TransitionOutcome.APPLIED), str(out))
    check("both SUSPENDED",
          (await task_status(factory, t), await execution_status(factory, e))
          == (TaskStatus.SUSPENDED.value, ExecutionStatus.SUSPENDED.value))

    async with factory() as s:
        again = await lsvc.suspend_after_resume_failure(s, task_id=t, execution_id=e)
    check("repeat call does not apply",
          again != (TransitionOutcome.APPLIED, TransitionOutcome.APPLIED), str(again))
    check("still SUSPENDED",
          await task_status(factory, t) == TaskStatus.SUSPENDED.value)

    t, e, _ = await make_running(started=True)
    async with factory() as s:
        out = await lsvc.suspend_after_resume_failure(s, task_id=t, execution_id=e)
    check("tool already started -> rejected",
          out == (TransitionOutcome.ILLEGAL, TransitionOutcome.CONFLICT), str(out))
    check("states remain RUNNING",
          (await task_status(factory, t), await execution_status(factory, e))
          == (TaskStatus.RUNNING.value, ExecutionStatus.RUNNING.value))

    waiting_task = await make_task(factory, thread_id, TaskStatus.WAITING_APPROVAL)
    waiting_exec = await make_execution(
        factory, waiting_task, ExecutionStatus.WAITING_APPROVAL)
    async with factory() as s:
        out = await lsvc.suspend_after_resume_failure(
            s, task_id=waiting_task, execution_id=waiting_exec)
    check("non-RUNNING rejected",
          out == (TransitionOutcome.CONFLICT, TransitionOutcome.CONFLICT), str(out))

    t, e, _ = await make_running()
    other_task = await make_task(factory, thread_id, TaskStatus.RUNNING)
    async with factory() as s:
        out = await lsvc.suspend_after_resume_failure(
            s, task_id=other_task, execution_id=e)
    check("scope mismatch",
          out == (TransitionOutcome.CONFLICT, TransitionOutcome.SCOPE_MISMATCH), str(out))

    t, e, _ = await make_running()
    try:
        async with factory() as s:
            await lsvc.suspend_after_resume_failure(
                s, task_id=t, execution_id=e, reason=SuspendReason.APPROVAL_TIMEOUT)
        check("non-RESUME_FAILED reason rejected", False)
    except ValueError:
        check("non-RESUME_FAILED reason rejected", True)

    t, e, _ = await make_running()
    original_exec = repository.transition_execution

    async def _fail(*args, **kwargs):
        return False

    repository.transition_execution = _fail
    try:
        async with factory() as s:
            out = await lsvc.suspend_after_resume_failure(
                s, task_id=t, execution_id=e)
    finally:
        repository.transition_execution = original_exec
    check("pair aborts on second failure",
          out == (TransitionOutcome.CONFLICT, TransitionOutcome.CONFLICT), str(out))
    check("both rolled back",
          (await task_status(factory, t), await execution_status(factory, e))
          == (TaskStatus.RUNNING.value, ExecutionStatus.RUNNING.value))


async def main() -> None:
    if DB.parent.exists():
        shutil.rmtree(DB.parent, ignore_errors=True)
    DB.parent.mkdir(parents=True, exist_ok=True)
    factory, engine = make_factory()
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    thread_id = await seed(factory)

    matrix_section()
    await repository_section(factory, thread_id)
    await service_single_section(factory, thread_id)
    await pair_section(factory, thread_id)
    await create_execution_section(factory, thread_id)
    await concurrency_section(factory, thread_id)
    await guarded_section(factory, thread_id)

    await engine.dispose()

    passed = sum(1 for _, o in _results if o)
    print(f"\n{passed}/{len(_results)} passed")
    if passed != len(_results):
        print("failed:")
        for label, o in _results:
            if not o:
                print("  -", label)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())

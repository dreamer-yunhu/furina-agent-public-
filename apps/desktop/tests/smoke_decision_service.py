"""T20 决策服务冒烟测试：持久化、幂等、冲突、终态、迟到、并发。

# ── AI-ASSISTED ── 本文件由 AI 生成，待人工复核 ──
# 复核重点：
#   · 并发段是**同进程、两个独立 Session + asyncio.gather**
#   · 数据库异常必须原样抛出，不能被映射成某个 outcome
#   · 判定顺序：已有决定优先于终态任务（用例 11）

跑法（仓库根）：
    .venv-build\\Scripts\\python.exe apps\\desktop\\tests\\smoke_decision_service.py
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

from sqlalchemy import delete, event, select  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402
from sqlmodel import SQLModel  # noqa: E402

from furina_core.models import AgentThreadID, User  # noqa: E402
from furina_core.task import repository  # noqa: E402
from furina_core.task.decision_service import (  # noqa: E402
    DecisionOutcome,
    submit_decision,
)
from furina_core.task.enums import ApprovalStatus, ExecutionStatus, TaskStatus  # noqa: E402
from furina_core.task.models import AgentExecution, AgentTask, ApprovalRequest  # noqa: E402
from furina_core.task.service import as_utc  # noqa: E402

PASS, FAIL = "PASS", "FAIL"
_results: list[tuple[str, bool]] = []


def check(label: str, ok: bool, extra: str = "") -> None:
    _results.append((label, ok))
    print(f"  [{PASS if ok else FAIL}] {label}" + (f"   {extra}" if extra else ""))


DB = ROOT / "_smoke_tmp" / "decision_service" / "t20.sqlite"


def make_factory():
    engine = create_async_engine(f"sqlite+aiosqlite:///{DB.as_posix()}")

    @event.listens_for(engine.sync_engine, "connect")
    def _fk(dbapi_connection, _record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return async_sessionmaker(bind=engine, expire_on_commit=False), engine


async def seed(factory):
    async with factory() as s:
        s.add(User(id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
                   user_name="local", hashed_password="", personal_preference=None))
        await s.commit()
        thread = AgentThreadID(
            user_id=uuid.UUID("00000000-0000-0000-0000-000000000001"), title="t20")
        s.add(thread)
        await s.commit()
        await s.refresh(thread)
        return thread.id


async def clear(factory):
    async with factory() as s:
        await s.execute(delete(ApprovalRequest))
        await s.execute(delete(AgentExecution))
        await s.execute(delete(AgentTask))
        await s.commit()


async def make_case(factory, thread_id, *, task_status=TaskStatus.WAITING_APPROVAL,
                    deadline_delta_minutes=5):
    async with factory() as s:
        task = await repository.create_task(
            s, thread_id=thread_id, instruction="t20", status=task_status)
    async with factory() as s:
        execution = await repository.create_execution(
            s, task_id=task.id,
            status=ExecutionStatus.RUNNING if task_status == TaskStatus.RUNNING
            else ExecutionStatus.WAITING_APPROVAL)
    async with factory() as s:
        approval = await repository.create_approval(
            s, task_id=task.id, execution_id=execution.id,
            tool_call_id=f"call-{uuid.uuid4().hex[:8]}",
            tool_name="write_file_tool", args_json="{}", args_hash="a" * 64,
            idempotency_key=uuid.uuid4().hex * 2,
            deadline_at=datetime.now(UTC) + timedelta(minutes=deadline_delta_minutes),
        )
    return task.id, execution.id, approval.id


async def approval_row(factory, approval_id):
    async with factory() as s:
        return await s.get(ApprovalRequest, approval_id)


async def task_status(factory, task_id):
    async with factory() as s:
        return (await s.get(AgentTask, task_id)).status


def decide_kwargs(task_id, execution_id, approval_id, decision=ApprovalStatus.APPROVED,
                  reason=None, now=None):
    return dict(
        approval_id=approval_id, task_id=task_id, execution_id=execution_id,
        decision=decision, decided_by="local", reason=reason, now=now,
    )


async def main() -> None:
    if DB.parent.exists():
        shutil.rmtree(DB.parent, ignore_errors=True)
    DB.parent.mkdir(parents=True, exist_ok=True)
    factory, engine = make_factory()
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    thread_id = await seed(factory)

    # ---------------------------------------------------------------- 1
    print("=== 1. 合法批准 ===")
    t, e, a = await make_case(factory, thread_id)
    async with factory() as s:
        result = await submit_decision(s, **decide_kwargs(t, e, a))
    row = await approval_row(factory, a)
    check("APPLIED", result.outcome is DecisionOutcome.APPLIED, result.outcome.value)
    check("status APPROVED", row.approval_status == ApprovalStatus.APPROVED.value)
    check("decided_by recorded", row.decided_by == "local")
    check("decided_at set", row.decided_at is not None)
    check("task untouched", await task_status(factory, t) == TaskStatus.WAITING_APPROVAL.value)
    first_decided_at = row.decided_at

    # ---------------------------------------------------------------- 2
    print("\n=== 2. 合法拒绝 ===")
    await clear(factory)
    t, e, a = await make_case(factory, thread_id)
    async with factory() as s:
        result = await submit_decision(
            s, **decide_kwargs(t, e, a, decision=ApprovalStatus.REJECTED, reason="no"))
    row = await approval_row(factory, a)
    check("APPLIED", result.outcome is DecisionOutcome.APPLIED, result.outcome.value)
    check("status REJECTED", row.approval_status == ApprovalStatus.REJECTED.value)
    check("reason stored", row.decision_reason == "no")

    # ---------------------------------------------------------------- 3
    print("\n=== 3. 相同决定重复提交（幂等）===")
    await clear(factory)
    t, e, a = await make_case(factory, thread_id)
    async with factory() as s:
        await submit_decision(s, **decide_kwargs(t, e, a))
    row_before = await approval_row(factory, a)
    async with factory() as s:
        result = await submit_decision(s, **decide_kwargs(t, e, a))
    row_after = await approval_row(factory, a)
    check("IDEMPOTENT", result.outcome is DecisionOutcome.IDEMPOTENT, result.outcome.value)
    check("decided_at unchanged",
          as_utc(row_after.decided_at) == as_utc(row_before.decided_at))
    check("decided_by unchanged", row_after.decided_by == "local")

    # ---------------------------------------------------------------- 4
    print("\n=== 4. 相反决定（冲突）===")
    async with factory() as s:
        result = await submit_decision(
            s, **decide_kwargs(t, e, a, decision=ApprovalStatus.REJECTED))
    row = await approval_row(factory, a)
    check("CONFLICT", result.outcome is DecisionOutcome.CONFLICT, result.outcome.value)
    check("original APPROVED preserved",
          row.approval_status == ApprovalStatus.APPROVED.value)

    # ---------------------------------------------------------------- 5/6
    print("\n=== 5-6. 不存在与关联错误 ===")
    async with factory() as s:
        result = await submit_decision(
            s, **decide_kwargs(t, e, uuid.uuid4()))
    check("NOT_FOUND", result.outcome is DecisionOutcome.NOT_FOUND)
    check("no row attached", result.approval is None)

    async with factory() as s:
        result = await submit_decision(
            s, **decide_kwargs(uuid.uuid4(), e, a))
    check("SCOPE_MISMATCH (task)", result.outcome is DecisionOutcome.SCOPE_MISMATCH)
    async with factory() as s:
        result = await submit_decision(
            s, **decide_kwargs(t, uuid.uuid4(), a))
    check("SCOPE_MISMATCH (execution)", result.outcome is DecisionOutcome.SCOPE_MISMATCH)
    check("wrong scope wrote nothing",
          (await approval_row(factory, a)).approval_status == ApprovalStatus.APPROVED.value)

    # ---------------------------------------------------------------- 7
    print("\n=== 7. 数据库故障必须抛出 ===")
    await clear(factory)
    t, e, a = await make_case(factory, thread_id)
    original_decide = repository.decide_approval

    async def _boom(*args, **kwargs):
        raise RuntimeError("db down")

    repository.decide_approval = _boom
    try:
        async with factory() as s:
            try:
                await submit_decision(s, **decide_kwargs(t, e, a))
                raised = False
            except RuntimeError:
                raised = True
    finally:
        repository.decide_approval = original_decide
    check("exception propagated", raised)
    check("nothing written",
          (await approval_row(factory, a)).approval_status == ApprovalStatus.PENDING.value)

    # ---------------------------------------------------------------- 8
    print("\n=== 8. 迟到决定（允许保存）===")
    await clear(factory)
    t, e, a = await make_case(factory, thread_id, deadline_delta_minutes=-10)
    async with factory() as s:
        result = await submit_decision(s, **decide_kwargs(t, e, a))
    check("APPLIED", result.outcome is DecisionOutcome.APPLIED, result.outcome.value)
    check("late=True", result.late is True)
    check("task still WAITING_APPROVAL",
          await task_status(factory, t) == TaskStatus.WAITING_APPROVAL.value)
    late_decided_at = (await approval_row(factory, a)).decided_at

    print("\n=== 8b. 迟到决定的幂等重放仍标记 late ===")
    async with factory() as s:
        replay = await submit_decision(s, **decide_kwargs(t, e, a))
    check("IDEMPOTENT", replay.outcome is DecisionOutcome.IDEMPOTENT, replay.outcome.value)
    check("late recomputed from stored decided_at", replay.late is True)
    check("decided_at unchanged",
          as_utc((await approval_row(factory, a)).decided_at) == as_utc(late_decided_at))

    # ---------------------------------------------------------------- 9
    print("\n=== 9. 终态任务收到批准 ===")
    await clear(factory)
    t, e, a = await make_case(factory, thread_id, task_status=TaskStatus.COMPLETED)
    async with factory() as s:
        result = await submit_decision(s, **decide_kwargs(t, e, a))
    check("ILLEGAL_STATE", result.outcome is DecisionOutcome.ILLEGAL_STATE, result.outcome.value)
    check("approval stays PENDING",
          (await approval_row(factory, a)).approval_status == ApprovalStatus.PENDING.value)

    # ---------------------------------------------------------------- 10
    print("\n=== 10. 两独立 Session 并发提交相反决定 ===")
    await clear(factory)
    t, e, a = await make_case(factory, thread_id)
    gate = asyncio.Event()

    async def worker(decision):
        async with factory() as s:
            await gate.wait()
            return await submit_decision(s, **decide_kwargs(t, e, a, decision=decision))

    async def opener():
        await asyncio.sleep(0.05)
        gate.set()

    r1, r2, _ = await asyncio.gather(
        worker(ApprovalStatus.APPROVED), worker(ApprovalStatus.REJECTED), opener())
    outcomes = {r1.outcome, r2.outcome}
    check("one APPLIED", outcomes == {DecisionOutcome.APPLIED, DecisionOutcome.CONFLICT},
          f"{r1.outcome.value}/{r2.outcome.value}")
    final = (await approval_row(factory, a)).approval_status
    check("exactly one effective decision",
          final in (ApprovalStatus.APPROVED.value, ApprovalStatus.REJECTED.value), final)
    async with factory() as s:
        rows = (await s.execute(select(ApprovalRequest))).scalars().all()
    check("no duplicate rows", len(rows) == 1, str(len(rows)))

    # ---------------------------------------------------------------- 11
    print("\n=== 11. 已决定优先于终态任务（判定顺序）===")
    await clear(factory)
    t, e, a = await make_case(factory, thread_id, task_status=TaskStatus.RUNNING)
    async with factory() as s:
        first = await submit_decision(s, **decide_kwargs(t, e, a))
    async with factory() as s:
        await repository.transition_task(
            s, task_id=t, from_status=TaskStatus.RUNNING, to_status=TaskStatus.COMPLETED)
    async with factory() as s:
        replay = await submit_decision(s, **decide_kwargs(t, e, a))
    check("first APPLIED", first.outcome is DecisionOutcome.APPLIED)
    check("replay after terminal is IDEMPOTENT",
          replay.outcome is DecisionOutcome.IDEMPOTENT, replay.outcome.value)

    # ---------------------------------------------------------------- 12
    print("\n=== 12. 非法决定值 ===")
    await clear(factory)
    t, e, a = await make_case(factory, thread_id)
    for bad in (ApprovalStatus.PENDING, ApprovalStatus.REVOKED):
        async with factory() as s:
            try:
                await submit_decision(s, **decide_kwargs(t, e, a, decision=bad))
                rejected = False
            except ValueError:
                rejected = True
        check(f"rejects {bad.value}", rejected)
    check("still PENDING",
          (await approval_row(factory, a)).approval_status == ApprovalStatus.PENDING.value)

    # ---------------------------------------------------------------- 13
    print("\n=== 13. 服务端时间 ===")
    await clear(factory)
    t, e, a = await make_case(factory, thread_id)
    before = datetime.now(UTC)
    async with factory() as s:
        result = await submit_decision(s, **decide_kwargs(t, e, a, now=None))
    after = datetime.now(UTC)
    stored = as_utc((await approval_row(factory, a)).decided_at)
    check("decided_at uses server time",
          before - timedelta(seconds=1) <= stored <= after + timedelta(seconds=1),
          f"{before} <= {stored} <= {after}")
    check("not late", result.late is False)

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

"""T21 冒烟：审批超时扫描与挂起。

# ── AI-ASSISTED ── 本文件由 AI 生成，待人工复核 ──
# 复核重点：
#   · 时间全部用注入的 `now`，不 sleep 等真实超时（仅后台循环启停用短间隔）
#   · 并发段是**同进程、两个独立 Session + asyncio.gather**；
#     跨进程与 PostgreSQL 未验证
#   · 个别分支（already_decided / 记录缺失）用 monkeypatch 构造，因为查询本身过滤了
#     PENDING，正常数据流走不到

跑法（仓库根）：
    .venv-build\\Scripts\\python.exe apps\\desktop\\tests\\smoke_timeout_scanner.py
"""
from __future__ import annotations

import asyncio
import shutil
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "apps" / "desktop" / "src"))
sys.path.insert(0, str(ROOT / "packages" / "core" / "src"))

from sqlalchemy import delete, event  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402
from sqlmodel import SQLModel  # noqa: E402

from furina_core.models import AgentThreadID, User  # noqa: E402
from furina_core.task import repository  # noqa: E402
from furina_core.task import timeout_scanner as scanner  # noqa: E402
from furina_core.task.enums import (
    ApprovalStatus,
    ExecutionStatus,
    TaskStatus,
)  # noqa: E402
from furina_core.task.lifecycle import TransitionOutcome  # noqa: E402
from furina_core.task.models import AgentExecution, AgentTask, ApprovalRequest  # noqa: E402
from furina_core.task.timeout_scanner import ScanReport, scan_once  # noqa: E402
from furina_desktop.services.timeout_scanner import (  # noqa: E402
    normalize_scan_settings,
    start_timeout_scanner,
    stop_timeout_scanner,
)

PASS, FAIL = "PASS", "FAIL"
_results: list[tuple[str, bool]] = []


def check(label: str, ok: bool, extra: str = "") -> None:
    _results.append((label, ok))
    print(f"  [{PASS if ok else FAIL}] {label}" + (f"   {extra}" if extra else ""))


DB = ROOT / "_smoke_tmp" / "timeout_scanner" / "t21.sqlite"


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
        s.add(User(id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
                   user_name="local", hashed_password="", personal_preference=None))
        await s.commit()
        thread = AgentThreadID(
            user_id=uuid.UUID("00000000-0000-0000-0000-000000000001"), title="t21")
        s.add(thread)
        await s.commit()
        await s.refresh(thread)
        return thread.id


async def make_case(
    factory,
    thread_id,
    *,
    deadline_at: datetime,
    task_status: TaskStatus = TaskStatus.WAITING_APPROVAL,
    execution_status: ExecutionStatus = ExecutionStatus.WAITING_APPROVAL,
    task_id: uuid.UUID | None = None,
    execution_task_id: uuid.UUID | None = None,
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    async with factory() as s:
        task = await repository.create_task(
            s, thread_id=thread_id, instruction="t21", status=task_status)
    async with factory() as s:
        execution = await repository.create_execution(
            s, task_id=execution_task_id or task.id, status=execution_status)
    async with factory() as s:
        approval = await repository.create_approval(
            s,
            task_id=task_id or task.id,
            execution_id=execution.id,
            tool_call_id=f"call-{uuid.uuid4().hex[:8]}",
            tool_name="write_file_tool",
            args_json="{}",
            args_hash="a" * 64,
            idempotency_key=uuid.uuid4().hex * 2,
            deadline_at=deadline_at,
        )
    return task.id, execution.id, approval.id


async def statuses(factory, task_id, execution_id):
    async with factory() as s:
        task = await s.get(AgentTask, task_id)
        execution = await s.get(AgentExecution, execution_id)
        return task.status, execution.status


async def approval_status(factory, approval_id) -> str:
    async with factory() as s:
        return (await s.get(ApprovalRequest, approval_id)).approval_status


async def clear_cases(factory) -> None:
    """清掉上一个小节的业务数据，避免到期审批被后续扫描重复捞到。"""
    async with factory() as s:
        await s.execute(delete(ApprovalRequest))
        await s.execute(delete(AgentExecution))
        await s.execute(delete(AgentTask))
        await s.commit()


async def main() -> None:
    if DB.parent.exists():
        shutil.rmtree(DB.parent, ignore_errors=True)
    DB.parent.mkdir(parents=True, exist_ok=True)
    factory, engine = make_factory()
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    thread_id = await seed(factory)
    now = datetime.now(UTC)

    calls: list[tuple[uuid.UUID, uuid.UUID]] = []

    async def hook(task_id, execution_id):
        calls.append((task_id, execution_id))

    # ---------------------------------------------------------------- 1
    print("=== 1. 未到期：不挂起 ===")
    await clear_cases(factory)
    t, e, a = await make_case(factory, thread_id, deadline_at=now + timedelta(minutes=10))
    report = await scan_once(factory, now=now, on_suspended=hook)
    check("no candidates", report.candidates == 0, str(report))
    check("nothing suspended", report.suspended == 0)
    check("state unchanged",
          await statuses(factory, t, e) == (TaskStatus.WAITING_APPROVAL.value,
                                            ExecutionStatus.WAITING_APPROVAL.value))

    # ---------------------------------------------------------------- 2/3
    print("\n=== 2-3. 到达截止时间：成对挂起，审批仍 PENDING ===")
    await clear_cases(factory)
    t, e, a = await make_case(factory, thread_id, deadline_at=now)
    report = await scan_once(factory, now=now, on_suspended=hook)
    check("boundary counted as due", report.candidates == 1 and report.suspended == 1,
          str(report))
    check("task SUSPENDED", (await statuses(factory, t, e))[0] == TaskStatus.SUSPENDED.value)
    check("execution SUSPENDED",
          (await statuses(factory, t, e))[1] == ExecutionStatus.SUSPENDED.value)
    check("approval still PENDING",
          await approval_status(factory, a) == ApprovalStatus.PENDING.value)
    check("hook called once", len(calls) == 1, str(len(calls)))

    # ---------------------------------------------------------------- 5
    print("\n=== 5. 已有决定的审批不处理（构造竞态窗口）===")
    await clear_cases(factory)
    t, e, a = await make_case(factory, thread_id, deadline_at=now - timedelta(minutes=5))
    async with factory() as s:
        await repository.decide_approval(
            s, approval_id=a, decision=ApprovalStatus.APPROVED,
            decided_by="local", decided_at=now)
    original_query = scanner.repository.list_due_pending_approvals

    async def _stale_query(session, *, now, limit):
        async with factory() as s2:
            return [await s2.get(ApprovalRequest, a)]

    scanner.repository.list_due_pending_approvals = _stale_query
    try:
        report = await scan_once(factory, now=now, on_suspended=hook)
    finally:
        scanner.repository.list_due_pending_approvals = original_query
    check("already_decided", report.already_decided == 1, str(report))
    check("not suspended", report.suspended == 0)

    # ---------------------------------------------------------------- 6
    print("\n=== 6. Task 终态：不迁移 ===")
    await clear_cases(factory)
    t, e, a = await make_case(
        factory, thread_id, deadline_at=now - timedelta(minutes=5),
        task_status=TaskStatus.COMPLETED)
    report = await scan_once(factory, now=now, on_suspended=hook)
    check("task_terminal", report.task_terminal == 1, str(report))
    check("task still COMPLETED",
          (await statuses(factory, t, e))[0] == TaskStatus.COMPLETED.value)

    # ---------------------------------------------------------------- 7
    print("\n=== 7. Task 非 WAITING_APPROVAL ===")
    await clear_cases(factory)
    t, e, a = await make_case(
        factory, thread_id, deadline_at=now - timedelta(minutes=5),
        task_status=TaskStatus.RUNNING)
    report = await scan_once(factory, now=now, on_suspended=hook)
    check("task_not_waiting", report.task_not_waiting == 1, str(report))

    # ---------------------------------------------------------------- 8/10
    print("\n=== 8/10. Execution 非 WAITING_APPROVAL（状态不一致）===")
    await clear_cases(factory)
    t, e, a = await make_case(
        factory, thread_id, deadline_at=now - timedelta(minutes=5),
        task_status=TaskStatus.WAITING_APPROVAL,
        execution_status=ExecutionStatus.RUNNING)
    report = await scan_once(factory, now=now, on_suspended=hook)
    check("execution_not_waiting", report.execution_not_waiting == 1, str(report))
    check("task untouched",
          (await statuses(factory, t, e))[0] == TaskStatus.WAITING_APPROVAL.value)

    # ---------------------------------------------------------------- 9
    print("\n=== 9. 关联不匹配：跳过并计数 ===")
    await clear_cases(factory)
    async with factory() as s:
        other_task = await repository.create_task(
            s, thread_id=thread_id, instruction="other", status=TaskStatus.QUEUED)
    t, e, a = await make_case(
        factory, thread_id, deadline_at=now - timedelta(minutes=5),
        task_id=other_task.id)  # approval.task_id 与 execution.task_id 不一致
    report = await scan_once(factory, now=now, on_suspended=hook)
    check("association_mismatch", report.association_mismatch == 1, str(report))

    # ---------------------------------------------------------------- 11
    print("\n=== 11. 关联记录缺失：跳过并计数 ===")
    await clear_cases(factory)
    fake = SimpleNamespace(id=uuid.uuid4(), execution_id=uuid.uuid4())

    async def _fake_query(session, *, now, limit):
        return [fake]

    scanner.repository.list_due_pending_approvals = _fake_query
    try:
        report = await scan_once(factory, now=now, on_suspended=hook)
    finally:
        scanner.repository.list_due_pending_approvals = original_query
    check("missing approval -> association_mismatch",
          report.association_mismatch == 1, str(report))

    # ---------------------------------------------------------------- 12
    print("\n=== 12. 重复扫描：不重复挂起、不重复回调 ===")
    await clear_cases(factory)
    before = len(calls)
    t, e, a = await make_case(factory, thread_id, deadline_at=now - timedelta(minutes=5))
    first = await scan_once(factory, now=now, on_suspended=hook)
    second = await scan_once(factory, now=now, on_suspended=hook)
    check("first suspended", first.suspended == 1, str(first))
    check("second does not suspend", second.suspended == 0, str(second))
    check("suspended pair excluded from candidates", second.candidates == 0, str(second))
    check("hook only once", len(calls) - before == 1)

    # ---------------------------------------------------------------- 13
    print("\n=== 13. 成对迁移冲突：不调用回调 ===")
    await clear_cases(factory)
    t, e, a = await make_case(factory, thread_id, deadline_at=now - timedelta(minutes=5))
    original_pair = scanner.lifecycle_service.transition_pair
    before = len(calls)

    async def _conflict_pair(*args, **kwargs):
        return TransitionOutcome.CONFLICT, TransitionOutcome.CONFLICT

    scanner.lifecycle_service.transition_pair = _conflict_pair
    try:
        report = await scan_once(factory, now=now, on_suspended=hook)
    finally:
        scanner.lifecycle_service.transition_pair = original_pair
    check("pair_conflict", report.pair_conflict == 1, str(report))
    check("hook not called on conflict", len(calls) == before)

    # ---------------------------------------------------------------- 14
    print("\n=== 14. 迁移失败：两表都不变 ===")
    await clear_cases(factory)
    t, e, a = await make_case(factory, thread_id, deadline_at=now - timedelta(minutes=5))
    original_exec = repository.transition_execution

    async def _fail_execution(*args, **kwargs):
        return False

    repository.transition_execution = _fail_execution
    try:
        report = await scan_once(factory, now=now, on_suspended=hook)
    finally:
        repository.transition_execution = original_exec
    check("pair_conflict", report.pair_conflict == 1, str(report))
    check("both rolled back",
          await statuses(factory, t, e) == (TaskStatus.WAITING_APPROVAL.value,
                                            ExecutionStatus.WAITING_APPROVAL.value))

    # ---------------------------------------------------------------- 15
    print("\n=== 15. 回调抛异常：状态不回滚 ===")
    await clear_cases(factory)
    t, e, a = await make_case(factory, thread_id, deadline_at=now - timedelta(minutes=5))

    async def bad_hook(task_id, execution_id):
        raise RuntimeError("hook boom")

    report = await scan_once(factory, now=now, on_suspended=bad_hook)
    check("suspended despite hook error", report.suspended == 1, str(report))
    check("callback_errors", report.callback_errors == 1, str(report))
    check("state committed",
          await statuses(factory, t, e) == (TaskStatus.SUSPENDED.value,
                                            ExecutionStatus.SUSPENDED.value))

    # ---------------------------------------------------------------- 16
    print("\n=== 16. 单条失败不影响其他候选 ===")
    await clear_cases(factory)
    t, e, a = await make_case(factory, thread_id, deadline_at=now - timedelta(minutes=5))

    async def _mixed_query(session, *, now, limit):
        async with factory() as s2:
            real = await s2.get(ApprovalRequest, a)
        return [SimpleNamespace(id=uuid.uuid4(), execution_id=uuid.uuid4()), real]

    scanner.repository.list_due_pending_approvals = _mixed_query
    try:
        report = await scan_once(factory, now=now, on_suspended=hook)
    finally:
        scanner.repository.list_due_pending_approvals = original_query
    check("one skipped", report.association_mismatch == 1, str(report))
    check("one suspended", report.suspended == 1, str(report))

    # ---------------------------------------------------------------- 17
    print("\n=== 17. 审批决定与扫描并发 ===")
    await clear_cases(factory)
    t, e, a = await make_case(factory, thread_id, deadline_at=now - timedelta(minutes=5))
    gate = asyncio.Event()

    async def decide_worker():
        async with factory() as s:
            await gate.wait()
            return await repository.decide_approval(
                s, approval_id=a, decision=ApprovalStatus.APPROVED,
                decided_by="local", decided_at=datetime.now(UTC))

    async def scan_worker():
        await gate.wait()
        return await scan_once(factory, now=now, on_suspended=hook)

    async def opener():
        await asyncio.sleep(0.05)
        gate.set()

    decided, scanned, _ = await asyncio.gather(decide_worker(), scan_worker(), opener())
    task_state, exec_state = await statuses(factory, t, e)
    final_approval = await approval_status(factory, a)
    legal = (
        (task_state == TaskStatus.SUSPENDED.value and exec_state == ExecutionStatus.SUSPENDED.value)
        or (task_state == TaskStatus.WAITING_APPROVAL.value
            and exec_state == ExecutionStatus.WAITING_APPROVAL.value)
    )
    check("decision committed", final_approval == ApprovalStatus.APPROVED.value,
          f"decided={decided}")
    check("state is a legal combination", legal,
          f"{task_state}/{exec_state}, scan={scanned}")

    # ---------------------------------------------------------------- 18
    print("\n=== 18. 两个独立 Session 并发扫描 ===")
    await clear_cases(factory)
    t, e, a = await make_case(factory, thread_id, deadline_at=now - timedelta(minutes=5))
    gate2 = asyncio.Event()

    async def worker():
        await gate2.wait()
        return await scan_once(factory, now=now, on_suspended=hook)

    async def opener2():
        await asyncio.sleep(0.05)
        gate2.set()

    r1, r2, _ = await asyncio.gather(worker(), worker(), opener2())
    total = r1.suspended + r2.suspended
    check("exactly one suspension", total == 1, f"{r1} | {r2}")
    check("task SUSPENDED",
          (await statuses(factory, t, e))[0] == TaskStatus.SUSPENDED.value)

    # ---------------------------------------------------------------- 19/20
    print("\n=== 19-20. 后台循环启停与关闭开关 ===")
    await clear_cases(factory)
    class DummyApp:
        def __init__(self):
            self.state = SimpleNamespace()

    loop_calls = {"n": 0}

    async def stub_scan(factory_arg, *, limit=50):
        loop_calls["n"] += 1
        return ScanReport()

    import furina_desktop.services.timeout_scanner as worker
    original_scan = worker.scan_once
    worker.scan_once = stub_scan
    try:
        app = DummyApp()
        status = start_timeout_scanner(
            app, session_factory=factory, interval=0.05, batch=10)
        check("status running", status == "running", status)
        await asyncio.sleep(0.16)
        check("loop executed", loop_calls["n"] >= 1, str(loop_calls))
        await stop_timeout_scanner(app)
        check("status stopped", app.state.timeout_scanner_status == "stopped")
        check("task cleared", app.state.timeout_scanner_task is None)

        disabled_app = DummyApp()
        before = loop_calls["n"]
        status = start_timeout_scanner(
            disabled_app, session_factory=factory, interval=0, batch=10)
        await asyncio.sleep(0.05)
        check("interval=0 disables", status == "disabled")
        check("no scan when disabled", loop_calls["n"] == before)
        await stop_timeout_scanner(disabled_app)
    finally:
        worker.scan_once = original_scan

    # ---------------------------------------------------------------- 21
    print("\n=== 21. 批量上限 ===")
    await clear_cases(factory)
    for _ in range(3):
        await make_case(factory, thread_id, deadline_at=now - timedelta(minutes=5))
    r = await scan_once(factory, now=now, limit=1, on_suspended=hook)
    check("limit respected", r.candidates == 1 and r.suspended == 1, str(r))
    r = await scan_once(factory, now=now, limit=2, on_suspended=hook)
    check("next round picks remaining", r.candidates == 2 and r.suspended == 2, str(r))

    # ---------------------------------------------------------------- 22
    print("\n=== 22. 配置归一化 ===")
    await clear_cases(factory)
    check("normal values unchanged", normalize_scan_settings(interval=30, batch=50) == (30, 50))
    check("negative interval -> 0", normalize_scan_settings(interval=-5, batch=50) == (0, 50))
    check("zero batch -> default", normalize_scan_settings(interval=30, batch=0) == (30, 50))
    check("zero interval stays 0", normalize_scan_settings(interval=0, batch=10) == (0, 10))

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

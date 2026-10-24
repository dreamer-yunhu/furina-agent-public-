"""T18 审批服务冒烟测试：幂等创建、冲突语义、UTC 归一化、跨任务校验。

# ── AI-ASSISTED ── 本文件由 AI 生成，待人工复核 ──
# 复核重点：并发用例依赖 SQLite 的写锁行为，换 PG 后要重新确认错误类型；
# 其余用例只依赖 service 契约，不依赖具体后端。

跑法（仓库根）：
    .venv-build\\Scripts\\python.exe apps\\desktop\\tests\\smoke_approval_service.py
"""
from __future__ import annotations

import asyncio
import shutil
import sys
import uuid
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "apps" / "desktop" / "src"))
sys.path.insert(0, str(ROOT / "packages" / "core" / "src"))

from sqlalchemy import event, select  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402
from sqlmodel import SQLModel  # noqa: E402

from furina_core.models import AgentThreadID, User  # noqa: E402
from furina_core.task.enums import ApprovalStatus, ToolExecutionStatus  # noqa: E402
from furina_core.task.models import ApprovalRequest  # noqa: E402
from furina_core.task.repository import (  # noqa: E402
    claim_tool_execution,
    create_execution,
    create_task,
    decide_approval,
    finish_tool_execution,
    get_approval,
)
from furina_core.task.service import (  # noqa: E402
    ApprovalConflict,
    as_utc,
    canonical_args_json,
    compute_args_hash,
    create_or_get_approval,
    derive_idempotency_key,
)
from furina_desktop.auth import LOCAL_USER_ID  # noqa: E402

PASS, FAIL = "PASS", "FAIL"
_results: list[tuple[str, bool]] = []


def check(label: str, ok: bool, extra: str = "") -> None:
    _results.append((label, ok))
    print(f"  [{PASS if ok else FAIL}] {label}" + (f"   {extra}" if extra else ""))


DB = ROOT / "_smoke_tmp" / "approval_service" / "t18.sqlite"


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
        s.add(User(id=LOCAL_USER_ID, user_name="local", hashed_password="", personal_preference=None))
        await s.commit()
        thread = AgentThreadID(user_id=LOCAL_USER_ID, title="t18")
        s.add(thread)
        await s.commit()
        await s.refresh(thread)
        task_a = await create_task(s, thread_id=thread.id, instruction="A")
        task_b = await create_task(s, thread_id=thread.id, instruction="B")
        exec_a = await create_execution(s, task_id=task_a.id)
        exec_a2 = await create_execution(s, task_id=task_a.id)
        return thread.id, task_a.id, task_b.id, exec_a.id, exec_a2.id


ARGS = {"file_path": "a.txt", "text": "hello"}
ARGS_OTHER = {"file_path": "a.txt", "text": "tampered"}


def kwargs(task_id, execution_id, *, tool_call_id="call_1", args=None, deadline=None):
    return dict(
        task_id=task_id,
        execution_id=execution_id,
        tool_call_id=tool_call_id,
        tool_name="write_file_tool",
        args=ARGS if args is None else args,
        deadline_at=deadline or (datetime.now(UTC) + timedelta(minutes=5)),
    )


async def count_rows(session, key: str) -> int:
    stmt = select(ApprovalRequest).where(ApprovalRequest.idempotency_key == key)
    return len((await session.execute(stmt)).scalars().all())


async def main() -> None:
    if DB.parent.exists():
        shutil.rmtree(DB.parent, ignore_errors=True)
    DB.parent.mkdir(parents=True, exist_ok=True)
    factory, engine = make_factory()
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

    thread_id, task_a, task_b, exec_a, exec_a2 = await seed(factory)

    # ---------------------------------------------------------------- 1
    print("=== 1. 参数规范化 ===")
    check("key order does not matter",
          canonical_args_json({"b": 1, "a": 2}) == canonical_args_json({"a": 2, "b": 1}))
    check("canonical form is compact & sorted",
          canonical_args_json({"b": 1, "a": 2}) == '{"a":2,"b":1}')
    check("same args -> same hash", compute_args_hash(ARGS) == compute_args_hash(dict(ARGS)))
    check("different args -> different hash", compute_args_hash(ARGS) != compute_args_hash(ARGS_OTHER))
    check("non-ascii stays readable", "中文" in canonical_args_json({"s": "中文"}))

    # ---------------------------------------------------------------- 2
    print("\n=== 2. 幂等键 ===")
    k1 = derive_idempotency_key(exec_a, "call_1")
    check("64 hex chars", len(k1) == 64 and all(c in "0123456789abcdef" for c in k1))
    check("uuid and str input agree", k1 == derive_idempotency_key(str(exec_a), "call_1"))
    check("different tool_call_id -> different key",
          k1 != derive_idempotency_key(exec_a, "call_2"))
    check("different execution -> different key",
          k1 != derive_idempotency_key(exec_a2, "call_1"))

    # ---------------------------------------------------------------- 3
    print("\n=== 3. 顺序重复创建（create-or-get）===")
    async with factory() as s:
        first, created1 = await create_or_get_approval(s, **kwargs(task_a, exec_a))
    async with factory() as s:
        again, created2 = await create_or_get_approval(s, **kwargs(task_a, exec_a))
        rows = await count_rows(s, derive_idempotency_key(exec_a, "call_1"))
    check("first call creates", created1 is True)
    check("second call reuses", created2 is False)
    check("same row id", first.id == again.id)
    check("only one row", rows == 1, f"rows={rows}")

    # ---------------------------------------------------------------- 4
    print("\n=== 4. 参数不一致 -> ApprovalConflict ===")
    async with factory() as s:
        try:
            await create_or_get_approval(s, **kwargs(task_a, exec_a, args=ARGS_OTHER))
            check("conflict raised", False, "no exception")
            row_before = None
        except ApprovalConflict as exc:
            check("conflict raised", True, str(exc)[:80])
            row_before = await get_approval(s, first.id)
        # SAVEPOINT 之后同一 session 仍可用
        check("session usable after conflict", row_before is not None)
        check("stored original args untouched",
              row_before is not None and row_before.args_hash == compute_args_hash(ARGS))
        # 同一 session 继续建另一条不同 key 的审批
        other, created = await create_or_get_approval(
            s, **kwargs(task_a, exec_a, tool_call_id="call_9"))
        check("session can still write", created is True and other.id is not None)

    # ---------------------------------------------------------------- 5
    print("\n=== 5. 跨任务错配 ===")
    async with factory() as s:
        try:
            await create_or_get_approval(
                s, **kwargs(task_b, exec_a, tool_call_id="call_cross"))
            check("cross-task mismatch rejected", False, "accepted")
        except ValueError as exc:
            check("cross-task mismatch rejected", True, str(exc)[:60])
        check("no row created for mismatch",
              await count_rows(s, derive_idempotency_key(exec_a, "call_cross")) == 0)

    # ---------------------------------------------------------------- 6
    print("\n=== 6. UTC 归一化 ===")
    naive = datetime(2026, 10, 24, 12, 0, 0)
    check("naive is interpreted as UTC", as_utc(naive) == naive.replace(tzinfo=UTC))
    aware_plus8 = datetime(2026, 10, 24, 12, 0, 0, tzinfo=timezone(timedelta(hours=8)))
    check("aware is converted to UTC", as_utc(aware_plus8) == datetime(2026, 10, 24, 4, 0, tzinfo=UTC))

    deadline = datetime.now(UTC) + timedelta(minutes=10)
    async with factory() as s:
        row, _ = await create_or_get_approval(
            s, **kwargs(task_a, exec_a, tool_call_id="call_tz", deadline=deadline))
    async with factory() as s:
        stored = await get_approval(s, row.id)
        check("sqlite returns naive", stored.deadline_at.tzinfo is None)
        check("as_utc restores the instant", as_utc(stored.deadline_at) == deadline)
        check("deadline comparison works",
              (datetime.now(UTC) < as_utc(stored.deadline_at)) is True)

    # ---------------------------------------------------------------- 7
    print("\n=== 7. 不同 execution 不复用审批 ===")
    async with factory() as s:
        r1, c1 = await create_or_get_approval(s, **kwargs(task_a, exec_a, tool_call_id="call_shared"))
    async with factory() as s:
        r2, c2 = await create_or_get_approval(s, **kwargs(task_a, exec_a2, tool_call_id="call_shared"))
    check("both created independently", c1 is True and c2 is True)
    check("different rows", r1.id != r2.id)

    # ---------------------------------------------------------------- 8
    print("\n=== 8. 并发同 key ===")
    gate = asyncio.Event()

    async def worker(call_id: str):
        async with factory() as s:
            await gate.wait()
            try:
                row, created = await create_or_get_approval(
                    s, **kwargs(task_a, exec_a, tool_call_id=call_id))
                return ("ok", row.id, created)
            except Exception as exc:  # noqa: BLE001
                return ("err", f"{type(exc).__name__}: {str(exc)[:50]}")

    async def opener():
        await asyncio.sleep(0.05)
        gate.set()

    # 同一个逻辑请求：key 由 execution+tool_call 决定，所以两侧必须传同一个 tool_call_id
    res = await asyncio.gather(worker("call_race"), worker("call_race"), opener())
    print("   ", res[0], res[1])
    ok = [r for r in res[:2] if r[0] == "ok"]
    check("both callers succeed", len(ok) == 2, str(res[:2]))
    check("both get the same row", len(ok) == 2 and ok[0][1] == ok[1][1])
    check("exactly one created", sum(1 for r in ok if r[2]) == 1)
    async with factory() as s:
        rows = await count_rows(s, derive_idempotency_key(exec_a, "call_race"))
    check("only one row persisted", rows == 1, f"rows={rows}")

    # ---------------------------------------------------------------- 9
    print("\n=== 9. 重复 finish 不覆盖既有结果 ===")
    async with factory() as s:
        row, _ = await create_or_get_approval(
            s, **kwargs(task_a, exec_a, tool_call_id="call_finish"))
    async with factory() as s:
        await decide_approval(s, approval_id=row.id, decision=ApprovalStatus.APPROVED,
                              decided_by="local", decided_at=datetime.now(UTC))
    async with factory() as s:
        check("claim ok", await claim_tool_execution(s, approval_id=row.id))
        await finish_tool_execution(s, approval_id=row.id,
                                    status=ToolExecutionStatus.SUCCEEDED, result="ok")
        await finish_tool_execution(s, approval_id=row.id,
                                    status=ToolExecutionStatus.FAILED, error="again")
    async with factory() as s:
        final = await get_approval(s, row.id)
    check("first result kept", final.tool_execution_status == ToolExecutionStatus.SUCCEEDED.value)
    check("result/error not overwritten",
          final.execution_result == "ok" and final.execution_error is None)

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

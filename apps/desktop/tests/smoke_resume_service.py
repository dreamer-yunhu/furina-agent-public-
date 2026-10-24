"""T22 冒烟：恢复前校验与成对恢复。

# ── AI-ASSISTED ── 本文件由 AI 生成，待人工复核 ──
# 复核重点：
#   · 文件校验使用临时沙箱目录，不碰仓库真实文件
#   · 并发段是**同进程、两个独立 Session + asyncio.gather**
#   · C7 只测 DB 内部一致性；图侧绑定属 T23，未测试

跑法（仓库根）：
    .venv-build\\Scripts\\python.exe apps\\desktop\\tests\\smoke_resume_service.py
"""
from __future__ import annotations

import asyncio
import hashlib
import shutil
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "apps" / "desktop" / "src"))
sys.path.insert(0, str(ROOT / "packages" / "core" / "src"))

from sqlalchemy import event  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402
from sqlmodel import SQLModel  # noqa: E402

from furina_core.models import AgentThreadID, User  # noqa: E402
from furina_core.task import repository  # noqa: E402
from furina_core.task import resume_service  # noqa: E402
from furina_core.task.enums import (  # noqa: E402
    ApprovalStatus,
    ExecutionStatus,
    TaskStatus,
)
from furina_core.task.models import AgentExecution, AgentTask, ApprovalRequest  # noqa: E402
from furina_core.task.resume_service import (  # noqa: E402
    ResumeOutcome,
    validate_and_resume,
)
from furina_core.task.service import canonical_args_json, compute_args_hash  # noqa: E402

PASS, FAIL = "PASS", "FAIL"
_results: list[tuple[str, bool]] = []


def check(label: str, ok: bool, extra: str = "") -> None:
    _results.append((label, ok))
    print(f"  [{PASS if ok else FAIL}] {label}" + (f"   {extra}" if extra else ""))


DB = ROOT / "_smoke_tmp" / "resume_service" / "t22.sqlite"
SANDBOX = ROOT / "_smoke_tmp" / "resume_service" / "sandbox"


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
            user_id=uuid.UUID("00000000-0000-0000-0000-000000000001"), title="t22")
        s.add(thread)
        await s.commit()
        await s.refresh(thread)
        return thread.id


async def make_case(factory, thread_id, *, task_status=TaskStatus.WAITING_APPROVAL,
                    exec_status=ExecutionStatus.WAITING_APPROVAL):
    async with factory() as s:
        task = await repository.create_task(
            s, thread_id=thread_id, instruction="t22", status=task_status)
    async with factory() as s:
        execution = await repository.create_execution(
            s, task_id=task.id, status=exec_status)
    return task.id, execution.id


async def add_approval(
    factory, task_id, execution_id, *, status=ApprovalStatus.PENDING,
    args=None, args_hash=None, target_path=None, old_hash=None,
    started=False, deadline_delta=5,
):
    args = args if args is not None else {"file_path": "a.txt", "text": "x"}
    async with factory() as s:
        approval = await repository.create_approval(
            s, task_id=task_id, execution_id=execution_id,
            tool_call_id=f"c-{uuid.uuid4().hex[:6]}",
            tool_name="write_file_tool",
            args_json=canonical_args_json(args),
            args_hash=args_hash or compute_args_hash(args),
            idempotency_key=uuid.uuid4().hex * 2,
            deadline_at=datetime.now(UTC) + timedelta(minutes=deadline_delta),
            target_path=target_path,
            old_hash=old_hash,
        )
    if status is not ApprovalStatus.PENDING:
        async with factory() as s:
            assert await repository.decide_approval(
                s, approval_id=approval.id, decision=status,
                decided_by="local", decided_at=datetime.now(UTC))
    if started:
        async with factory() as s:
            assert await repository.claim_tool_execution(s, approval_id=approval.id)
    return approval.id


async def states(factory, task_id, execution_id):
    async with factory() as s:
        task = await s.get(AgentTask, task_id)
        execution = await s.get(AgentExecution, execution_id)
        return task.status, execution.status


async def approval_row(factory, approval_id):
    async with factory() as s:
        return await s.get(ApprovalRequest, approval_id)


def file_hash(text: str) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


async def run(factory, task_id, execution_id):
    async with factory() as s:
        return await validate_and_resume(
            s, task_id=task_id, execution_id=execution_id,
            workspace_root=SANDBOX)


async def main() -> None:
    if DB.parent.exists():
        shutil.rmtree(DB.parent, ignore_errors=True)
    DB.parent.mkdir(parents=True, exist_ok=True)
    SANDBOX.mkdir(parents=True, exist_ok=True)
    factory, engine = make_factory()
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    thread_id = await seed(factory)

    # ---------------------------------------------------------------- 1
    print("=== 1. WAITING_APPROVAL + APPROVED -> RESUMED ===")
    t, e = await make_case(factory, thread_id)
    a = await add_approval(factory, t, e, status=ApprovalStatus.APPROVED,
                           target_path=None)
    result = await run(factory, t, e)
    check("RESUMED", result.outcome is ResumeOutcome.RESUMED, result.outcome.value)
    check("both RUNNING",
          await states(factory, t, e) == (TaskStatus.RUNNING.value,
                                          ExecutionStatus.RUNNING.value))
    check("approval unchanged",
          (await approval_row(factory, a)).approval_status == ApprovalStatus.APPROVED.value)

    # ---------------------------------------------------------------- 2
    print("\n=== 2. SUSPENDED + 迟到批准 -> RESUMED ===")
    t, e = await make_case(
        factory, thread_id, task_status=TaskStatus.SUSPENDED,
        exec_status=ExecutionStatus.SUSPENDED)
    a = await add_approval(factory, t, e, status=ApprovalStatus.APPROVED,
                           target_path=None, deadline_delta=-30)
    result = await run(factory, t, e)
    check("RESUMED despite past deadline", result.outcome is ResumeOutcome.RESUMED,
          result.outcome.value)

    # ---------------------------------------------------------------- 3
    print("\n=== 3. 同批仍有 PENDING -> PENDING_APPROVALS ===")
    t, e = await make_case(factory, thread_id)
    await add_approval(factory, t, e, status=ApprovalStatus.APPROVED, target_path=None)
    await add_approval(factory, t, e, status=ApprovalStatus.PENDING, target_path=None)
    result = await run(factory, t, e)
    check("PENDING_APPROVALS", result.outcome is ResumeOutcome.PENDING_APPROVALS,
          result.outcome.value)
    check("state unchanged",
          await states(factory, t, e) == (TaskStatus.WAITING_APPROVAL.value,
                                          ExecutionStatus.WAITING_APPROVAL.value))

    # ---------------------------------------------------------------- 4/5
    print("\n=== 4-5. REJECTED / REVOKED -> NOT_APPROVED ===")
    for decision in (ApprovalStatus.REJECTED, ApprovalStatus.REVOKED):
        t, e = await make_case(factory, thread_id)
        await add_approval(factory, t, e, status=decision, target_path=None)
        result = await run(factory, t, e)
        check(f"{decision.value} -> NOT_APPROVED",
              result.outcome is ResumeOutcome.NOT_APPROVED, result.outcome.value)

    # ---------------------------------------------------------------- 6/7/8
    print("\n=== 6-8. 状态不允许 -> ILLEGAL_STATE ===")
    t, e = await make_case(
        factory, thread_id, task_status=TaskStatus.COMPLETED,
        exec_status=ExecutionStatus.COMPLETED)
    await add_approval(factory, t, e, status=ApprovalStatus.APPROVED, target_path=None)
    result = await run(factory, t, e)
    check("terminal task rejected", result.outcome is ResumeOutcome.ILLEGAL_STATE,
          result.outcome.value)

    t, e = await make_case(
        factory, thread_id, task_status=TaskStatus.RUNNING,
        exec_status=ExecutionStatus.RUNNING)
    await add_approval(factory, t, e, status=ApprovalStatus.APPROVED, target_path=None)
    result = await run(factory, t, e)
    check("RUNNING pair rejected", result.outcome is ResumeOutcome.ILLEGAL_STATE,
          result.outcome.value)

    t, e = await make_case(
        factory, thread_id, task_status=TaskStatus.WAITING_APPROVAL,
        exec_status=ExecutionStatus.SUSPENDED)
    await add_approval(factory, t, e, status=ApprovalStatus.APPROVED, target_path=None)
    result = await run(factory, t, e)
    check("mixed states rejected", result.outcome is ResumeOutcome.ILLEGAL_STATE,
          result.outcome.value)

    # ---------------------------------------------------------------- 9
    print("\n=== 9. 工具已开始 -> ALREADY_EXECUTED ===")
    t, e = await make_case(factory, thread_id)
    await add_approval(factory, t, e, status=ApprovalStatus.APPROVED,
                       target_path=None, started=True)
    result = await run(factory, t, e)
    check("ALREADY_EXECUTED", result.outcome is ResumeOutcome.ALREADY_EXECUTED,
          result.outcome.value)

    # ---------------------------------------------------------------- 10
    print("\n=== 10. DB 参数快照不一致 -> ARGS_MISMATCH ===")
    t, e = await make_case(factory, thread_id)
    await add_approval(factory, t, e, status=ApprovalStatus.APPROVED,
                       args_hash="b" * 64, target_path=None)
    result = await run(factory, t, e)
    check("ARGS_MISMATCH", result.outcome is ResumeOutcome.ARGS_MISMATCH,
          result.outcome.value)

    # ---------------------------------------------------------------- 11
    print("\n=== 11. old_hash 不匹配 -> OLD_HASH_MISMATCH ===")
    target = SANDBOX / "changed.txt"
    target.write_text("hello", encoding="utf-8")
    t, e = await make_case(factory, thread_id)
    await add_approval(factory, t, e, status=ApprovalStatus.APPROVED,
                       target_path="changed.txt", old_hash=file_hash("old"))
    result = await run(factory, t, e)
    check("OLD_HASH_MISMATCH", result.outcome is ResumeOutcome.OLD_HASH_MISMATCH,
          result.outcome.value)
    check("file untouched", target.read_text(encoding="utf-8") == "hello")
    check("state unchanged",
          await states(factory, t, e) == (TaskStatus.WAITING_APPROVAL.value,
                                          ExecutionStatus.WAITING_APPROVAL.value))

    # ---------------------------------------------------------------- 12
    print("\n=== 12. old_hash=None 且文件已存在 -> OLD_HASH_MISMATCH ===")
    created = SANDBOX / "created.txt"
    created.write_text("someone", encoding="utf-8")
    t, e = await make_case(factory, thread_id)
    await add_approval(factory, t, e, status=ApprovalStatus.APPROVED,
                       target_path="created.txt", old_hash=None)
    result = await run(factory, t, e)
    check("OLD_HASH_MISMATCH", result.outcome is ResumeOutcome.OLD_HASH_MISMATCH,
          result.outcome.value)

    # ---------------------------------------------------------------- 13
    print("\n=== 13. old_hash=None 且文件不存在（新文件）-> RESUMED ===")
    t, e = await make_case(factory, thread_id)
    await add_approval(factory, t, e, status=ApprovalStatus.APPROVED,
                       target_path="new-file.txt", old_hash=None)
    result = await run(factory, t, e)
    check("RESUMED", result.outcome is ResumeOutcome.RESUMED, result.outcome.value)

    # ---------------------------------------------------------------- 14
    print("\n=== 14. target_path=None 跳过文件校验 ===")
    t, e = await make_case(factory, thread_id)
    await add_approval(factory, t, e, status=ApprovalStatus.APPROVED,
                       target_path=None, old_hash="c" * 64)
    result = await run(factory, t, e)
    check("RESUMED", result.outcome is ResumeOutcome.RESUMED, result.outcome.value)

    # ---------------------------------------------------------------- 15/16
    print("\n=== 15-16. NOT_FOUND / SCOPE_MISMATCH ===")
    async with factory() as s:
        result = await validate_and_resume(
            s, task_id=uuid.uuid4(), execution_id=uuid.uuid4(),
            workspace_root=SANDBOX)
    check("NOT_FOUND", result.outcome is ResumeOutcome.NOT_FOUND, result.outcome.value)

    t, e = await make_case(factory, thread_id)
    await add_approval(factory, t, e, status=ApprovalStatus.APPROVED, target_path=None)
    other_task, _ = await make_case(factory, thread_id)
    async with factory() as s:
        result = await validate_and_resume(
            s, task_id=other_task, execution_id=e, workspace_root=SANDBOX)
    check("SCOPE_MISMATCH", result.outcome is ResumeOutcome.SCOPE_MISMATCH,
          result.outcome.value)

    t2, e2 = await make_case(factory, thread_id)
    result = await run(factory, t2, e2)
    check("no approvals -> NOT_FOUND", result.outcome is ResumeOutcome.NOT_FOUND,
          result.outcome.value)

    # ---------------------------------------------------------------- 17
    print("\n=== 17. 两独立 Session 并发恢复 ===")
    t, e = await make_case(
        factory, thread_id, task_status=TaskStatus.SUSPENDED,
        exec_status=ExecutionStatus.SUSPENDED)
    await add_approval(factory, t, e, status=ApprovalStatus.APPROVED, target_path=None)
    gate = asyncio.Event()

    async def worker():
        await gate.wait()
        async with factory() as s:
            return await validate_and_resume(
                s, task_id=t, execution_id=e, workspace_root=SANDBOX)

    async def opener():
        await asyncio.sleep(0.05)
        gate.set()

    r1, r2, _ = await asyncio.gather(worker(), worker(), opener())
    resumed = sum(1 for r in (r1, r2) if r.outcome is ResumeOutcome.RESUMED)
    check("exactly one RESUMED", resumed == 1,
          f"{r1.outcome.value}/{r2.outcome.value}")
    check("final state RUNNING",
          await states(factory, t, e) == (TaskStatus.RUNNING.value,
                                          ExecutionStatus.RUNNING.value))

    # ---------------------------------------------------------------- 18
    print("\n=== 18. 迁移失败注入：无半迁移 ===")
    t, e = await make_case(factory, thread_id)
    await add_approval(factory, t, e, status=ApprovalStatus.APPROVED, target_path=None)
    original = repository.transition_execution

    async def _fail(*args, **kwargs):
        return False

    repository.transition_execution = _fail
    try:
        result = await run(factory, t, e)
    finally:
        repository.transition_execution = original
    check("not RESUMED", result.outcome is not ResumeOutcome.RESUMED, result.outcome.value)
    check("both rolled back",
          await states(factory, t, e) == (TaskStatus.WAITING_APPROVAL.value,
                                          ExecutionStatus.WAITING_APPROVAL.value))

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

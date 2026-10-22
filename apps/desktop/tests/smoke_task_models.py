"""阶段 A 冒烟：任务层级三张表 + SQLite 约束。

跑法（仓库根）：
    .venv-build\\Scripts\\python.exe apps\\desktop\\tests\\smoke_task_models.py

验的是"数据库真的在约束"，不是"代码长得对"：
    1. init_db 建出 user / agentthreadid / agent_task / agent_execution / approval_request
    2. 本地用户被 seed，且重复 init 不重复插入
    3. 外键真的生效（不存在的 thread_id 被拒）
    4. idempotency_key / redelegation_key / graph_thread_id 唯一约束生效
    5. 状态迁移是条件 UPDATE（第二次抢不到）
    6. CHECK 约束写进了 DDL

⚠️ 用仓库内路径，不用 tempfile：这台机器的 %TEMP% 有写入限制
（见 smoke_checkpoint.py 的说明）。
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

from fastapi import FastAPI  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.exc import IntegrityError  # noqa: E402

from furina_core.models import AgentThreadID, User  # noqa: E402
from furina_core.task.enums import (  # noqa: E402
    ApprovalStatus,
    ExecutionStatus,
    TaskStatus,
    ToolExecutionStatus,
)
from furina_core.task.repository import (  # noqa: E402
    claim_tool_execution,
    create_approval,
    create_execution,
    create_task,
    decide_approval,
    finish_tool_execution,
    get_approval,
    transition_execution,
    transition_task,
)
from furina_desktop.auth import LOCAL_USER_ID  # noqa: E402
from furina_desktop.storage.database import init_db  # noqa: E402

PASS, FAIL = "PASS", "FAIL"
_results: list[tuple[str, bool]] = []


def check(label: str, ok: bool, extra: str = "") -> None:
    _results.append((label, ok))
    print(f"  [{PASS if ok else FAIL}] {label}" + (f"   {extra}" if extra else ""))


async def main() -> None:
    tmpdir = ROOT / "_smoke_tmp" / "stage_a"
    if tmpdir.exists():
        shutil.rmtree(tmpdir, ignore_errors=True)
    tmpdir.mkdir(parents=True, exist_ok=True)
    db = tmpdir / "furina.db"

    app = FastAPI()
    await init_db(app, db_path=db)
    await init_db(app, db_path=db)  # 幂等
    factory = app.state.async_session

    print("=== 1. 建表与 seed ===")
    async with factory() as s:
        rows = (
            await s.execute(
                text("SELECT name FROM sqlite_master WHERE type='table'")
            )
        ).scalars().all()
    need = {"user", "agentthreadid", "agent_task", "agent_execution", "approval_request"}
    check("五张表都存在", need.issubset(set(rows)), f"实得 {sorted(rows)}")

    async with factory() as s:
        user = await s.get(User, LOCAL_USER_ID)
        user_count = (
            await s.execute(text("SELECT COUNT(*) FROM user"))
        ).scalar_one()
    check("本地用户已 seed", user is not None)
    check("重复 init 不重复 seed", user_count == 1, f"user 行数={user_count}")

    print("\n=== 2. 外键生效 ===")
    async with factory() as s:
        try:
            await create_task(
                s,
                thread_id=uuid.uuid4(),  # 不存在的 thread
                instruction="should fail",
            )
            check("不存在的 thread_id 被外键拒绝", False, "竟然插入成功")
        except IntegrityError:
            await s.rollback()
            check("不存在的 thread_id 被外键拒绝", True)

    # 准备一条合法 thread
    async with factory() as s:
        thread = AgentThreadID(user_id=LOCAL_USER_ID, title="t")
        s.add(thread)
        await s.commit()
        await s.refresh(thread)
        thread_id = thread.id
    check("合法线程可创建（本地用户外键成立）", True, str(thread_id))

    print("\n=== 3. 正常建 Task / Execution / Approval ===")
    async with factory() as s:
        task = await create_task(s, thread_id=thread_id, instruction="写文件")
        check("Task 初始状态 QUEUED", task.status == TaskStatus.QUEUED.value)
        execution = await create_execution(s, task_id=task.id)
        check(
            "Execution.graph_thread_id == execution_id",
            execution.graph_thread_id == str(execution.id),
        )
        approval = await create_approval(
            s,
            task_id=task.id,
            execution_id=execution.id,
            tool_call_id="call_1",
            tool_name="write_file_tool",
            args_json='{"file_path":"a.txt","text":"x"}',
            args_hash="a" * 64,
            idempotency_key="k" * 64,
            deadline_at=datetime.now(UTC) + timedelta(minutes=5),
        )
        check("Approval 初始 PENDING / NOT_STARTED",
              approval.approval_status == ApprovalStatus.PENDING.value
              and approval.tool_execution_status == ToolExecutionStatus.NOT_STARTED.value)
        task_id, execution_id, approval_id = task.id, execution.id, approval.id

    print("\n=== 4. 唯一约束 ===")
    async with factory() as s:
        try:
            await create_approval(
                s, task_id=task_id, execution_id=execution_id,
                tool_call_id="call_2", tool_name="write_file_tool",
                args_json="{}", args_hash="b" * 64,
                idempotency_key="k" * 64,  # 与上一条相同
                deadline_at=datetime.now(UTC) + timedelta(minutes=5),
            )
            check("idempotency_key 唯一约束生效", False, "重复插入成功")
        except IntegrityError:
            await s.rollback()
            check("idempotency_key 唯一约束生效", True)

    async with factory() as s:
        await create_task(s, thread_id=thread_id, instruction="child-1",
                          redelegation_key="r" * 64)
    async with factory() as s:
        try:
            await create_task(s, thread_id=thread_id, instruction="child-2",
                              redelegation_key="r" * 64)
            check("redelegation_key 唯一约束生效", False, "重复插入成功")
        except IntegrityError:
            await s.rollback()
            check("redelegation_key 唯一约束生效", True)
    async with factory() as s:
        await create_task(s, thread_id=thread_id, instruction="normal-1")
        await create_task(s, thread_id=thread_id, instruction="normal-2")
        check("多个 NULL redelegation_key 可共存", True)

    async with factory() as s:
        try:
            await create_execution(s, task_id=task_id,
                                   graph_thread_id=execution.graph_thread_id)
            check("graph_thread_id 唯一约束生效", False, "重复插入成功")
        except IntegrityError:
            await s.rollback()
            check("graph_thread_id 唯一约束生效", True)

    print("\n=== 5. 条件状态迁移 ===")
    async with factory() as s:
        ok1 = await transition_task(
            s, task_id=task_id, from_status=TaskStatus.QUEUED,
            to_status=TaskStatus.RUNNING,
        )
        ok2 = await transition_task(
            s, task_id=task_id, from_status=TaskStatus.QUEUED,
            to_status=TaskStatus.RUNNING,
        )
    check("第一次 QUEUED→RUNNING 成功", ok1)
    check("第二次抢不到（条件 UPDATE）", not ok2)

    async with factory() as s:
        ok3 = await transition_execution(
            s, execution_id=execution_id,
            from_status=ExecutionStatus.CREATED,
            to_status=ExecutionStatus.RUNNING,
        )
        ok4 = await transition_execution(
            s, execution_id=execution_id,
            from_status=ExecutionStatus.CREATED,
            to_status=ExecutionStatus.RUNNING,
        )
    check("Execution 迁移同样只能抢一次", ok3 and not ok4)

    print("\n=== 6. 审批决定与执行认领 ===")
    async with factory() as s:
        done = await decide_approval(
            s, approval_id=approval_id, decision=ApprovalStatus.APPROVED,
            decided_by="local", decided_at=datetime.now(UTC),
        )
        again = await decide_approval(
            s, approval_id=approval_id, decision=ApprovalStatus.REJECTED,
            decided_by="local", decided_at=datetime.now(UTC),
        )
    check("PENDING→APPROVED 成功", done)
    check("终态不能再次决定", not again)

    async with factory() as s:
        claimed = await claim_tool_execution(s, approval_id=approval_id)
        claimed_again = await claim_tool_execution(s, approval_id=approval_id)
    check("执行认领成功", claimed)
    check("同一审批不能被认领两次", not claimed_again)

    async with factory() as s:
        await finish_tool_execution(
            s, approval_id=approval_id,
            status=ToolExecutionStatus.SUCCEEDED, result="ok",
        )
        row = await get_approval(s, approval_id)
    check("执行结果与审批状态分离",
          row.approval_status == ApprovalStatus.APPROVED.value
          and row.tool_execution_status == ToolExecutionStatus.SUCCEEDED.value)

    print("\n=== 7. CHECK 约束写进 DDL ===")
    async with factory() as s:
        ddl = (
            await s.execute(
                text("SELECT sql FROM sqlite_master WHERE name='agent_task'")
            )
        ).scalar_one()
    check("agent_task 有 status CHECK", "CHECK" in ddl.upper(), ddl[:80])

    ok = sum(1 for _, o in _results if o)
    print(f"\n{ok}/{len(_results)} 通过")
    if ok != len(_results):
        print("失败项:")
        for label, o in _results:
            if not o:
                print("  -", label)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())

# ── AI-ASSISTED ── 本文件由 AI 生成，待人工复核 ──
"""任务层级表与 SQLite 约束（由 smoke_task_models.py 原生化）。

验的是"数据库真的在约束"，不是"代码长得对"：
    · 表与 seed 幂等
    · 外键真的生效
    · 唯一约束（idempotency_key / redelegation_key / graph_thread_id）
    · 状态迁移是条件 UPDATE（第二次抢不到）
    · 审批决定与执行状态是两条独立的状态机
    · CHECK 写进了 DDL

原脚本是一条长流程；这里拆成 3 个用例、各自独立建库，失败定位更准。
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from furina_core.models import AgentThreadID, User
from furina_core.task.enums import (
    ApprovalStatus,
    ExecutionStatus,
    TaskStatus,
    ToolExecutionStatus,
)
from furina_core.task.repository import (
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
from furina_desktop.auth import LOCAL_USER_ID
from furina_desktop.storage.database import init_db


async def make_factory(tmp_path):
    """建库并**重复 init 一次**（幂等由用例 1 断言）。"""
    app = FastAPI()
    db_path = tmp_path / "furina.db"
    await init_db(app, db_path=db_path)
    await init_db(app, db_path=db_path)
    return app.state.async_session


async def seed(factory):
    """建线程 + Task + Execution + Approval，返回各类 id。"""
    async with factory() as session:
        thread = AgentThreadID(user_id=LOCAL_USER_ID, title="t")
        session.add(thread)
        await session.commit()
        await session.refresh(thread)
        thread_id = thread.id

    async with factory() as session:
        task = await create_task(session, thread_id=thread_id, instruction="写文件")
        execution = await create_execution(session, task_id=task.id)
        approval = await create_approval(
            session,
            task_id=task.id,
            execution_id=execution.id,
            tool_call_id="call_1",
            tool_name="write_file_tool",
            args_json='{"file_path":"a.txt","text":"x"}',
            args_hash="a" * 64,
            idempotency_key="k" * 64,
            deadline_at=datetime.now(UTC) + timedelta(minutes=5),
        )
        return {
            "thread_id": thread_id,
            "task_id": task.id,
            "execution_id": execution.id,
            "approval_id": approval.id,
            "graph_thread_id": execution.graph_thread_id,
        }


def test_schema_seed_and_foreign_key(tmp_path):
    async def scenario():
        factory = await make_factory(tmp_path)

        async with factory() as session:
            rows = (
                await session.execute(
                    text("SELECT name FROM sqlite_master WHERE type='table'")
                )
            ).scalars().all()
        need = {
            "user",
            "agentthreadid",
            "agent_task",
            "agent_execution",
            "approval_request",
        }
        assert need.issubset(set(rows)), sorted(rows)

        async with factory() as session:
            user = await session.get(User, LOCAL_USER_ID)
            user_count = (
                await session.execute(text("SELECT COUNT(*) FROM user"))
            ).scalar_one()
        assert user is not None
        assert user_count == 1, f"重复 init 重复 seed：user 行数={user_count}"

        # 外键：不存在的 thread_id 必须被数据库拒绝
        async with factory() as session:
            with pytest.raises(IntegrityError):
                await create_task(session, thread_id=uuid.uuid4(), instruction="should fail")
            await session.rollback()

    asyncio.run(scenario())


def test_uniqueness_constraints(tmp_path):
    async def scenario():
        factory = await make_factory(tmp_path)
        ids = await seed(factory)

        # idempotency_key 唯一
        async with factory() as session:
            with pytest.raises(IntegrityError):
                await create_approval(
                    session,
                    task_id=ids["task_id"],
                    execution_id=ids["execution_id"],
                    tool_call_id="call_2",
                    tool_name="write_file_tool",
                    args_json="{}",
                    args_hash="b" * 64,
                    idempotency_key="k" * 64,
                    deadline_at=datetime.now(UTC) + timedelta(minutes=5),
                )
            await session.rollback()

        # redelegation_key 唯一；NULL 可共存
        async with factory() as session:
            await create_task(
                session,
                thread_id=ids["thread_id"],
                instruction="child-1",
                redelegation_key="r" * 64,
            )
        async with factory() as session:
            with pytest.raises(IntegrityError):
                await create_task(
                    session,
                    thread_id=ids["thread_id"],
                    instruction="child-2",
                    redelegation_key="r" * 64,
                )
            await session.rollback()
        async with factory() as session:
            await create_task(session, thread_id=ids["thread_id"], instruction="normal-1")
            await create_task(session, thread_id=ids["thread_id"], instruction="normal-2")

        # graph_thread_id 唯一
        async with factory() as session:
            with pytest.raises(IntegrityError):
                await create_execution(
                    session,
                    task_id=ids["task_id"],
                    graph_thread_id=ids["graph_thread_id"],
                )
            await session.rollback()

    asyncio.run(scenario())


def test_state_transitions_and_claiming(tmp_path):
    async def scenario():
        factory = await make_factory(tmp_path)
        ids = await seed(factory)

        # 条件 UPDATE：同样的迁移只能抢成功一次
        async with factory() as session:
            first = await transition_task(
                session,
                task_id=ids["task_id"],
                from_status=TaskStatus.QUEUED,
                to_status=TaskStatus.RUNNING,
            )
            second = await transition_task(
                session,
                task_id=ids["task_id"],
                from_status=TaskStatus.QUEUED,
                to_status=TaskStatus.RUNNING,
            )
        assert first is True
        assert second is False

        async with factory() as session:
            exec_first = await transition_execution(
                session,
                execution_id=ids["execution_id"],
                from_status=ExecutionStatus.CREATED,
                to_status=ExecutionStatus.RUNNING,
            )
            exec_second = await transition_execution(
                session,
                execution_id=ids["execution_id"],
                from_status=ExecutionStatus.CREATED,
                to_status=ExecutionStatus.RUNNING,
            )
        assert exec_first is True and exec_second is False

        # 审批决定：终态不可再次决定
        async with factory() as session:
            decided = await decide_approval(
                session,
                approval_id=ids["approval_id"],
                decision=ApprovalStatus.APPROVED,
                decided_by="local",
                decided_at=datetime.now(UTC),
            )
            again = await decide_approval(
                session,
                approval_id=ids["approval_id"],
                decision=ApprovalStatus.REJECTED,
                decided_by="local",
                decided_at=datetime.now(UTC),
            )
        assert decided is True and again is False

        # 执行认领：同一审批只能认领一次
        async with factory() as session:
            claimed = await claim_tool_execution(session, approval_id=ids["approval_id"])
            claimed_again = await claim_tool_execution(
                session, approval_id=ids["approval_id"]
            )
        assert claimed is True and claimed_again is False

        # 审批状态与执行状态分离
        async with factory() as session:
            await finish_tool_execution(
                session,
                approval_id=ids["approval_id"],
                status=ToolExecutionStatus.SUCCEEDED,
                result="ok",
            )
            row = await get_approval(session, ids["approval_id"])
        assert row.approval_status == ApprovalStatus.APPROVED.value
        assert row.tool_execution_status == ToolExecutionStatus.SUCCEEDED.value

        # CHECK 约束写进 DDL
        async with factory() as session:
            ddl = (
                await session.execute(
                    text("SELECT sql FROM sqlite_master WHERE name='agent_task'")
                )
            ).scalar_one()
        assert "CHECK" in ddl.upper(), ddl[:120]

    asyncio.run(scenario())

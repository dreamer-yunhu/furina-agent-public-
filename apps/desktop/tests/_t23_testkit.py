"""T23 冒烟测试的共享夹具：临时业务库 + AgentRuntime + 线程。

只在测试进程里用；不进产品代码。
"""

from __future__ import annotations

import uuid
from pathlib import Path

from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

from furina_core.models import AgentThreadID, User
from furina_desktop.agent.runtime import AgentRuntime, set_runtime


async def make_runtime(root: Path, *, sandbox: Path, timeout: int = 600):
    """建 SQLite 业务库、seed 用户、返回 (engine, factory, runtime, user_id)。"""
    root.mkdir(parents=True, exist_ok=True)
    engine = create_async_engine(f"sqlite+aiosqlite:///{(root / 'business.db').as_posix()}")

    @event.listens_for(engine.sync_engine, "connect")
    def _fk(dbapi_connection, _record):
        cur = dbapi_connection.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

    user_id = uuid.uuid4()
    async with factory() as session:
        session.add(User(id=user_id, user_name=f"t23-{user_id.hex[:8]}", hashed_password=""))
        await session.commit()

    runtime = AgentRuntime(factory, workspace_root=sandbox, approval_timeout_seconds=timeout)
    set_runtime(runtime)
    return engine, factory, runtime, user_id


async def new_thread(factory, user_id: uuid.UUID, title: str = "t23") -> uuid.UUID:
    thread_id = uuid.uuid4()
    async with factory() as session:
        session.add(AgentThreadID(id=thread_id, title=title, user_id=user_id))
        await session.commit()
    return thread_id


def run_input(instruction: str, run) -> dict:
    return {
        "messages": [{"role": "user", "content": instruction}],
        "mode": "code",
        "subagent_task": instruction,
        "task_id": str(run.task_id),
        "execution_id": str(run.execution_id),
    }


def config_for(run) -> dict:
    return {"configurable": {"thread_id": run.graph_thread_id}}

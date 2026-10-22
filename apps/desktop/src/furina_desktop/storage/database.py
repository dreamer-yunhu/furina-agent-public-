"""桌面版业务数据库 —— SQLite。

它和 checkpoint 存储是**两个库、两个文件**：

    data/furina.db           业务表：user / agentthreadid / agent_task /
                              agent_execution / approval_request
    data/checkpoints.sqlite  LangGraph 的 checkpoints / writes

分开的理由：checkpoint 表是 LangGraph 的外部契约，业务表将来要迁移；
混在一个文件里会让"换 checkpoint 实现"变成高风险操作。

⚠️ 与 web 的差异：desktop 是单用户、单进程（有单实例锁），
   所以这里不引入连接池调优、不做多 worker 协调。
"""

# ── AI-ASSISTED ── 本文件由 AI 生成/改写，待人工复核 ──
# 复核重点：
#   1. ★ SQLite 默认**不启用外键**。这里用 connect 事件执行
#      `PRAGMA foreign_keys=ON`，否则 agent_task.thread_id 等外键只是装饰。
#   2. `create_all` 只建新表，不改旧表。V2 只新增表，所以够用；
#      下一次要改列时必须引入 Alembic。
#   3. 本地用户必须先 seed：auth.py 返回的是**不落库**的固定 UUID，
#      而 agentthreadid.user_id 是外键。不 seed 的话，建 Thread 会失败。

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

from furina_core.models import User
from furina_desktop.auth import LOCAL_USER_ID

# 确保三张任务表在 SQLModel.metadata 里注册；没有这行，create_all 不会建它们。
import furina_core.task.models  # noqa: F401  (import for side effect)


def default_db_path() -> Path:
    """业务库默认位置。与 checkpoint 的过渡策略一致：先落在 CWD 的 data/。"""
    return Path("data") / "furina.db"


async def init_db(app: FastAPI, db_path: str | Path | None = None) -> None:
    """建立 SQLite 引擎、建表、seed 本地用户。**幂等**。"""
    if getattr(app.state, "db_engine", None) is not None:
        return

    path = Path(db_path or default_db_path()).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)

    engine = create_async_engine(
        f"sqlite+aiosqlite:///{path.as_posix()}",
        pool_pre_ping=True,
    )

    @event.listens_for(engine.sync_engine, "connect")
    def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    session_factory = async_sessionmaker(
        bind=engine,
        expire_on_commit=False,
    )

    app.state.db_engine = engine
    app.state.async_session = session_factory

    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

    await _seed_local_user(session_factory)


async def _seed_local_user(session_factory: async_sessionmaker[AsyncSession]) -> None:
    """把桌面版固定用户写进库。

    没有它，`agentthreadid.user_id` 的外键会拒绝创建任何线程。
    """
    async with session_factory() as session:
        if await session.get(User, LOCAL_USER_ID) is not None:
            return
        session.add(
            User(
                id=LOCAL_USER_ID,
                user_name="本地用户",
                hashed_password="",  # 单机无口令；字段非空是表结构要求
                personal_preference=None,
            )
        )
        await session.commit()


async def close_db(app: FastAPI) -> None:
    engine = getattr(app.state, "db_engine", None)
    if engine is not None:
        await engine.dispose()
        app.state.db_engine = None
        app.state.async_session = None

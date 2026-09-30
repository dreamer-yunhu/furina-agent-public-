"""通用的数据库会话依赖 —— 两边共用。

═══════════════════════════════════════════════════════════════════════
为什么把它单独拆出来
═══════════════════════════════════════════════════════════════════════

原 `backend/app/core/database.py` 把三件事混在一个文件里：

    ① `get_session`      —— FastAPI 依赖，从 app.state 取会话工厂   → **通用**
    ② `init_db/close_db` —— 建 PG 引擎 + 连接池                     → **PG 专属**
    ③ `create_table`     —— `SQLModel.metadata.create_all`         → **看谁调用**

拆开之后：

    `furina_core.storage.session`  ← 本文件（通用，依赖注入）
    `furina_web.storage.database`  ← PG 引擎与建表（web 专属）

**为什么②不能进 core**：它 `create_async_engine(settings.pg_url)` ——
桌面版用 SQLite，根本不连 PG。把 PG 引擎塞进共享内核，
等于让 desktop 白背一个 asyncpg 依赖（那正是重构要消除的东西）。

═══════════════════════════════════════════════════════════════════════
⚠️ 一个必须知道的约定：会话工厂放在 app.state
═══════════════════════════════════════════════════════════════════════

本文件**不创建**会话工厂，只从 `request.app.state.async_session` 取。
所以每个 app 必须在自己的 lifespan 里先把工厂挂上去：

    app.state.async_session = async_sessionmaker(bind=engine, ...)

否则这个依赖会在**第一个请求**时报 `AttributeError`（找不到 `async_session`），
而不是启动时报错 —— 排障时注意这个时机差。
"""

# ── AI-ASSISTED ── 本文件由 AI 生成/改写，待人工复核 ──
# 复核重点：
#   1. 逻辑**逐字搬运**自原 `core/database.py` 的 `get_session`，只改了文件位置与注释。
#   2. `async_sessionmaker` 只用来做**类型标注**，实际对象从 app.state 取 ——
#      这个"标注与来源分离"的写法有点绕，但它是原作者的风格，我没改。
#   3. 原文件还有 `init_db` / `close_db` / `create_table`，已分别去
#      web 侧（PG 专属）。**desktop 将来要用 SQLite 时，需要自己写这三个**。

from __future__ import annotations

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


async def get_session(request: Request) -> AsyncSession:
    """依赖注入：每次请求获取一个数据库会话。

    用法：

        @router.get("/x")
        async def x(session: AsyncSession = Depends(get_session)):
            ...

    ⚠️ 前提：app 的 lifespan 里已经把 `async_sessionmaker` 挂到
    `app.state.async_session`。没挂的话，这里会抛 `AttributeError`
    —— 而且是在**请求进来时**，不是启动时。
    """
    factory: async_sessionmaker = request.app.state.async_session
    async with factory() as session:
        yield session

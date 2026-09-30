"""桌面版的生命周期管理 —— 建立/关闭 checkpoint 存储。

═══════════════════════════════════════════════════════════════════════
演进：从 PG 到 SQLite（以及为什么文件被拆过）
═══════════════════════════════════════════════════════════════════════

**第一刀：拆文件。** 原 `storage/agent_graph.py` 一个文件干了两件事：

    ① `init_pg_saver` / `close_pg_saver`  —— 连接的开关      → 存储层
    ② `build_graph(saver)` + `app.state.graph` —— 组装主管图 → 编排层

而且 ① 里 `from furina_desktop.agent.graph import build_graph` ——
**存储层反向依赖了编排层**。后果：想换存储就必须动 storage/，而动 storage/
又会牵到 agent/ —— 两件不相关的事被绑在一起。

**第二刀：换实现。** 桌面版的产品定义是"开箱即用"→ 用户不能为了用它装 PostgreSQL。
所以 checkpointer 换成 SQLite（`langgraph-checkpoint-sqlite`）。

    换掉的东西：AsyncPostgresSaver / AsyncConnectionPool / dict_row
                / `dsn = settings.pg_url.replace("postgresql+asyncpg", "postgresql")` 那个 hack
    换来的东西：SqliteCheckpointStore（见 storage/local_store.py）

**副作用（好事）**：`psycopg` / `psycopg-pool` 两个依赖可以从 desktop 删掉 ——
它们只在这个文件里用过。

═══════════════════════════════════════════════════════════════════════
⚠️ 一个必须知道的时机问题
═══════════════════════════════════════════════════════════════════════

`AsyncSqliteSaver.setup()`（建表）是**幂等的**，而且被 `aget_tuple` / `alist` / `aput`
**自动调用**。所以 SQLite 版**没有"启动期建表失败"这个错误** ——
"表不存在"这类报错的第一次出现，会是在**首次对话**，而不是启动时。

排障时别往启动日志里找。
"""

# ── AI-ASSISTED ── 本文件由 AI 生成/改写，待人工复核 ──
# 复核重点：
#   1. ★ 本文件从 PG 换成了 SQLite，**依据是 wheel 源码里的 api.py**（不是文档猜测）：
#      `AsyncSqliteSaver.__init__(conn, *, serde=None)`、`setup()` 幂等、
#      `from_conn_string` 是 `@asynccontextmanager`（所以不能用它做长生命周期对象）。
#   2. `app.state.graph` 的写入**仍然没有**（它属于编排层）。
#      应用入口应该这样组装（见文件末尾的示例）。
#   3. `get_saver` 的返回类型我用了 `SqliteCheckpointStore` 具体类。
#      更干净的做法是标成 `furina_core.checkpoint.CheckpointStore` 协议 ——
#      但那样 `api/agent.py` 要 import core，改动更大。留给你决定。

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request

from furina_desktop.storage.local_store import SqliteCheckpointStore


def default_db_path() -> Path:
    """默认的数据库位置。

    ⚠️ 现在是"当前工作目录下的 data/"，**这只是过渡**。
       桌面版发布后应该落在用户数据目录：
           Windows: %APPDATA%\\furina-agent\\checkpoints.sqlite
           macOS:   ~/Library/Application Support/furina-agent/
           Linux:   ~/.local/share/furina-agent/
       用 `platformdirs` 库一行解决，但那是新依赖 —— 留到 M4 定。
    """
    return Path("data") / "checkpoints.sqlite"


async def init_checkpoint_store(app: FastAPI, db_path: str | Path | None = None) -> None:
    """建立 checkpoint 存储并挂到 app.state。**幂等**（重复调用会直接返回）。

    ⚠️ 注意它**不组装图**。图由应用入口用 `agent.build.build_graph(store)` 组装，
       因为"怎么装图"是编排层的事，不是存储层的事。
    """
    if getattr(app.state, "checkpoint_store", None) is not None:
        return  # 幂等：lifespan 可能被重复触发（测试里常见）

    store = SqliteCheckpointStore(db_path or default_db_path())
    await store.open()
    # setup() 会建表。SQLite 版它是幂等的、且各读写方法会自动调用，
    # 这里显式调一次是为了**让建表错误在启动时就暴露**，而不是等到首次对话。
    await store.setup()
    app.state.checkpoint_store = store


async def close_checkpoint_store(app: FastAPI) -> None:
    """关闭连接。

    ⚠️ **必须调**：Windows 上不关会锁住 .sqlite 文件，用户删目录/卸载会失败。
    """
    store = getattr(app.state, "checkpoint_store", None)
    if store is not None:
        await store.close()
        app.state.checkpoint_store = None


async def get_saver(request: Request) -> SqliteCheckpointStore:
    """依赖注入：把 checkpoint 存储交给路由。

    用法（路由里）：

        async def delete_thread(..., saver=Depends(get_saver)):
            await saver.adelete_thread(str(thread_id))
    """
    return request.app.state.checkpoint_store


# ══════════════════════════════════════════════════════════════════════
# 应用入口该怎么组装（M0/M4 要写的代码，现在还不存在）
# ══════════════════════════════════════════════════════════════════════
#
#     from contextlib import asynccontextmanager
#     from fastapi import FastAPI
#
#     from furina_desktop.agent.build import build_graph
#     from furina_desktop.storage.lifespan import init_checkpoint_store, close_checkpoint_store
#
#     @asynccontextmanager
#     async def lifespan(app: FastAPI):
#         await init_checkpoint_store(app)                       # 存储层：开连接
#         app.state.graph = build_graph(app.state.checkpoint_store)   # 编排层：装图
#         yield
#         await close_checkpoint_store(app)                      # 存储层：关连接
#
#     app = FastAPI(lifespan=lifespan)
#
# **注意这个顺序**：先有 store，才能装图 —— 因为 `build_graph` 需要它做 checkpointer。
# 这也解释了为什么"图的装配"不该在存储层里（存储层不该知道图需要什么）。

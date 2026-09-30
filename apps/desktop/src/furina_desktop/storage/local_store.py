"""桌面端的 agent 状态存储 —— SQLite 实现。

═══════════════════════════════════════════════════════════════════════
一、为什么是 SQLite（而不是 PG）
═══════════════════════════════════════════════════════════════════════

桌面版的产品定义是"开箱即用" → **用户不能为了用它而安装 PostgreSQL**。

    web 版：Postgres + Redis（多用户、公网入口、需要横向扩展）
    desktop：SQLite + LanceDB（单用户、本地、零外部服务）

两者都实现 `furina_core.checkpoint.CheckpointStore` 协议，
**所以业务代码（routers / services）不需要知道自己跑在哪一边。**

═══════════════════════════════════════════════════════════════════════
二、⭐ 一个关键的库事实：setup() 不用手工调
═══════════════════════════════════════════════════════════════════════

从 wheel 源码（`langgraph/checkpoint/sqlite/aio.py`）**实测确认**：

    · `setup()` 内部有 `if self.is_setup: return` → **幂等**
    · `aget_tuple` / `alist` / `aput` / `aput_writes` 第一行都是
      `await self.setup()` → **自动建表，不用手工调**
    · `setup()` 里的 DDL 第一条就是 `PRAGMA journal_mode=WAL`

这跟 **Postgres 版不一样**：Postgres 需要显式 `await saver.setup()`
（原实现在 `core/agent_graph.py:27` 就是手工调的）。
所以本类提供 `setup()` 只是为了**协议一致**，调它无害也无必要。

⚠️ **推论**：本实现**没有"建表失败"这个启动期错误** ——
第一次读/写数据时才会建表。所以"没建表"的报错会出现在**首次对话**，
而不是启动时。这一点要知道，否则排障会找错方向。

═══════════════════════════════════════════════════════════════════════
三、为什么自己持有连接，而不是用 from_conn_string
═══════════════════════════════════════════════════════════════════════

库提供了 `AsyncSqliteSaver.from_conn_string(path)`，但它是个
**`@asynccontextmanager`**：

    async with AsyncSqliteSaver.from_conn_string("db.sqlite") as saver:
        ...
        # 出了 with 块，连接就被关了

**但我们的 saver 必须是长期存活对象**（挂在 `app.state` 上，跨请求复用）。
用 with 块 = 每个请求开一次连接 = 每次都要重新建表检查 + WAL 切换。

所以这里**自己管连接**：一个 `aiosqlite.Connection` 活到应用关闭，
`close()` 里显式关掉它。

⚠️ **Windows 特有**：SQLite 文件不关的话，**文件会被锁住** ——
用户卸载应用或删目录时会失败。所以 `close()` 不是可选的。
"""

# ── AI-ASSISTED ── 本文件由 AI 生成/改写，待人工复核 ──
# 复核重点：
#   1. ★ 本文件是**照着 wheel 源码写的**（不是照文档猜的）。
#      依据：`.venv-build/Lib/site-packages/.../aio.py` 的
#      `__init__(conn, *, serde=None)` / `setup()` 幂等 / 各方法自动 setup。
#      但它**还没跑过**（见文件末尾的验证命令）。
#   2. `setup()` 我保留了，虽然库会自动调 —— 为了协议一致。
#      如果你觉得多余，删掉它不影响功能。
#   3. `close()` 是我加的（库里没有）。**别删** —— 见上面 Windows 文件锁的说明。

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Sequence
from pathlib import Path
from typing import Any

import aiosqlite
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

logger = logging.getLogger(__name__)


class SqliteCheckpointStore:
    """`CheckpointStore` 协议的 SQLite 实现。

    用法（在 lifespan 里）：

        store = SqliteCheckpointStore(db_path)
        await store.open()                    # 建连接（不建表，见下）
        app.state.checkpoint_store = store
        graph = build_graph(store)            # 图只依赖协议
        ...
        await store.close()                   # 关闭时务必调

    注意 `open()` 与 `setup()` 是**两件事**：
        open()   建立连接（必须，否则后面全报错）
        setup()  建表（可选 —— 库会在首次读写时自动建）
    """

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = Path(db_path)
        self._conn: aiosqlite.Connection | None = None
        self._saver: AsyncSqliteSaver | None = None

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------
    async def open(self) -> None:
        """建立连接。**必须在任何读写之前调用。**

        目录不存在就创建 —— `%APPDATA%\\furina-agent\\` 在首次运行时不存在。
        """
        if self._conn is not None:
            return  # 幂等

        self._db_path.parent.mkdir(parents=True, exist_ok=True)

        # isolation_level=None 让 aiosqlite 走**自动提交**模式。
        # 理由：LangGraph 的写入是"单条 INSERT 就是一个完整事务"，
        # 不需要跨语句事务。开着隐式事务反而会让并发写互相锁住。
        self._conn = await aiosqlite.connect(self._db_path, isolation_level=None)
        self._saver = AsyncSqliteSaver(self._conn)
        logger.info("[checkpoint] SQLite 已连接: %s", self._db_path)

    async def setup(self) -> None:
        """建表。**幂等**（库内部有 `is_setup` 短路，且 DDL 全是 `CREATE TABLE IF NOT EXISTS`）。

        实际上不调也行（首次读写会自动建），保留它是为了协议一致。
        """
        await self._require_saver().setup()

    async def close(self) -> None:
        """关闭连接。

        ⚠️ **必须调**：Windows 上不关会锁住数据库文件，导致用户删不掉目录。
        """
        if self._conn is not None:
            await self._conn.close()
            logger.info("[checkpoint] SQLite 连接已关闭")
        self._conn = None
        self._saver = None

    async def __aenter__(self) -> SqliteCheckpointStore:
        await self.open()
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.close()

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------
    def _require_saver(self) -> AsyncSqliteSaver:
        if self._saver is None:
            raise RuntimeError(
                "checkpoint store 还没打开 —— 先 await store.open()。"
                "（在 lifespan 里调用，别等到请求进来才开）"
            )
        return self._saver

    @property
    def db_path(self) -> Path:
        return self._db_path

    @property
    def saver(self) -> AsyncSqliteSaver:
        """底层的 LangGraph saver —— **给"装配图"用的**。

        ⚠️ 为什么需要暴露它：LangGraph 的 `compile(checkpointer=...)` 有类型检查，
           只认 `BaseCheckpointSaver`；而本类是个**适配器**（实现的是
           `furina_core.checkpoint.CheckpointStore` 协议）。所以装配图时必须解包。

        分工是清楚的：
            业务层（routers / services）  → 用本类（协议），不碰 `.saver`
            装配层（agent.build.build_graph）→ 用 `.saver` 解包后交给 LangGraph

        ⚠️ `build_graph` 通过 `getattr(obj, "saver", None)` 找它 ——
           所以**这个属性的名字不能改**，改了装配就静默拿到 None、
           然后报 "Invalid checkpointer provided"。
        """
        return self._require_saver()

    # ------------------------------------------------------------------
    # CheckpointStore 协议：读
    # ------------------------------------------------------------------
    async def aget_tuple(self, config: Any) -> Any | None:
        return await self._require_saver().aget_tuple(config)

    async def alist(
        self,
        config: Any | None,
        *,
        filter: dict[str, Any] | None = None,
        before: Any | None = None,
        limit: int | None = None,
    ) -> AsyncIterator[Any]:
        """列出检查点。

        注意实现方式：库里的 `alist` 是 **async generator**（`async def` + `yield`），
        所以这里要 `async for ... yield`，**不能直接 return** ——
        直接 return 一个 async generator 对象会让调用方多 await 一层。
        """
        async for item in self._require_saver().alist(
            config, filter=filter, before=before, limit=limit
        ):
            yield item

    # ------------------------------------------------------------------
    # CheckpointStore 协议：写
    # ------------------------------------------------------------------
    async def aput(
        self,
        config: Any,
        checkpoint: Any,
        metadata: Any,
        new_versions: Any,
    ) -> Any:
        return await self._require_saver().aput(config, checkpoint, metadata, new_versions)

    async def aput_writes(
        self,
        config: Any,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        await self._require_saver().aput_writes(config, writes, task_id, task_path)

    # ------------------------------------------------------------------
    # CheckpointStore 协议：删
    # ------------------------------------------------------------------
    async def adelete_thread(self, thread_id: str) -> None:
        """删掉一个 thread 的全部数据。

        ⚠️ 业务侧 `DELETE /agent/threads/{id}` 必须走到这里，否则留孤儿数据。
        原实现在 `services/agent_thread.py` 里还有一段语义相反的死代码
        （`if not fact: await saver.adelete_thread(...)`），迁移时一并清掉。
        """
        await self._require_saver().adelete_thread(thread_id)


# ══════════════════════════════════════════════════════════════════════
# 验证命令（本文件还没跑过 —— 先跑这个）
# ══════════════════════════════════════════════════════════════════════
#
#   cd C:\furina-agent
#   uv run --package furina-desktop python apps/desktop/tests/smoke_checkpoint.py
#
# 断言清单（写在那个 smoke 脚本里）：
#   1. open() 后，db 文件被创建
#   2. setup() 后，checkpoints / checkpoint_writes / checkpoint_blobs 三张表存在
#   3. aget_tuple(不存在的 thread) 返回 None（不是抛异常）
#   4. aput → aget_tuple 能读回来，且返回的 config 里有 checkpoint_id
#   5. adelete_thread 之后，三张表里该 thread 的记录为 0
#   6. close() 之后，SQLite 文件句柄被释放（Windows 上能删掉文件）

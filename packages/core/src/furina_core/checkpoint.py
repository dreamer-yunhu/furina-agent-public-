"""agent 状态的持久化协议 —— 把"存在哪"从业务代码里隔离出来。

═══════════════════════════════════════════════════════════════════════
一、为什么需要这一层（本轮决策，见 docs/DESKTOP-PLAN.md §4.4）
═══════════════════════════════════════════════════════════════════════

现状问题：LangGraph 的 saver 被**直接 import 在 4 个文件里**：

    services/agent_thread.py      AsyncPostgresSaver
    core/agent_graph.py           AsyncPostgresSaver
    routers/agent.py              AsyncPostgresSaver
    repositories/agent_thread_id.py  AsyncPostgresSaver

后果有三个：

1. **换存储 = 改多处**。而存储**本来就要分叉**：web 用 PG，desktop 用 SQLite。
2. **表结构是它的**。`checkpoints` / `checkpoint_blobs` / `checkpoint_writes` 三张表
   是 LangGraph 的格式 —— 一旦落库，就成了**外部承诺**（换格式意味着迁移历史数据）。
3. **想换掉 LangGraph 时，替换点散在各处**。抽一层之后，它变成**一个插入点**。

═══════════════════════════════════════════════════════════════════════
二、设计取舍：协议对齐上游，而不是自定义
═══════════════════════════════════════════════════════════════════════

**关键决定：本协议的读/写/删方法，是照 LangGraph 的 saver 契约定义的。**
**准确的账（2026 本轮核对上游源码后更正，原文写的是"6 个方法 1:1"，不对）**：

    上游 `BaseCheckpointSaver` 的 async 方法有 6 个：
        aget / aget_tuple / alist / aput / aput_writes / adelete_thread
    本协议声明其中的 **5 个**（省略 `aget` —— 它只是 `aget_tuple` 的包装，
    上游实现就是 `if value := await self.aget_tuple(config): return value.checkpoint`），
    再加 **2 个生命周期方法**（setup / close），合计 **7 个成员**。

理由：如果自定义一套"更好看"的接口，就需要在每个 LangGraph 调用点做双向适配，
而**适配层本身就是要维护的代码**。对齐上游的好处是：

    · LangGraph 的 saver 天然满足本协议（结构化类型，不需要继承）
    · 业务代码只依赖本协议 → 换实现时业务代码一行不改
    · 将来真要用别的图引擎（比如 Rust 重写），只需实现这 7 个方法

上游契约出处（本机实测，`.venv-build/Lib/site-packages/langgraph/checkpoint/base/__init__.py`）：

    aget 416 / aget_tuple 428 / alist 442 / aput 467 / aput_writes 490 / adelete_thread 510

⚠️ **本文件刻意不 import langgraph**。用 `Any` 代替它的类型，
   因为 core 不该被任何图引擎绑死（红线是"零存储后端 + 不依赖具体引擎"，
   见 `furina_core/__init__.py`）。
   代价：类型检查器帮不上忙。收益：换引擎时只改实现，不改业务代码。

═══════════════════════════════════════════════════════════════════════
三、生命周期：为什么有 setup() 和 close()
═══════════════════════════════════════════════════════════════════════

    setup()   建表。Postgres 需要它建三张表；SQLite 也需要（首次运行）。
              幂等：重复调用不应报错。
    close()   释放连接。**Postgres 尤其重要**（连接池不关会泄漏）；
              SQLite 也要关，否则文件句柄留着、Windows 上还会锁文件。

两者都不在上游的 6 个方法里 —— 上游只管"读写状态"，不管"怎么起怎么关"。
但**应用确实需要它们**（现在的 `core/agent_graph.py` 就是在 lifespan 里手动做这两件事）。
所以本协议**补上这两个**，与上面 5 个合计 7 个成员。
"""

# ── AI-ASSISTED ── 本文件由 AI 生成/改写，待人工复核 ──
# 复核重点：
#   1. ★ 6 个方法名与签名是**照上游 1:1 抄的**，别"优化"它们 ——
#      改名会导致 LangGraph 的 saver 不再满足本协议（结构化类型按名字匹配）。
#   2. 用 `Any` 代替 LangGraph 的 `Checkpoint` / `CheckpointTuple` 等类型，
#      是为了让 core 零依赖。**代价是类型检查器完全帮不上忙** ——
#      如果你觉得这个代价太大，可以改成"只在 typing.TYPE_CHECKING 下 import"，
#      那是标准做法，我留给你决定。
#   3. `setup()` 的幂等性**没有任何强制力**（协议表达不了）。
#      实现者必须自己保证，否则第二次启动就炸。

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class CheckpointStore(Protocol):
    """agent 状态的存储。

    **结构化类型**：不要求继承，只要方法名和签名对得上就行。
    这意味着 LangGraph 的 `AsyncSqliteSaver` / `AsyncPostgresSaver`
    **开箱即满足本协议**（实测它们的 `__init__.py` 就是这样定义的）。

    业务代码（routers / services）只应依赖本协议，**不要 import 具体 saver**。
    """

    # ------------------------------------------------------------------
    # 生命周期（上游契约之外，但应用需要）
    # ------------------------------------------------------------------
    async def setup(self) -> None:
        """建立所需的表/索引。**必须幂等**（重复调用不报错）。

        Postgres：建 checkpoints / checkpoint_blobs / checkpoint_writes 三张表。
        SQLite：首次运行建表（并启用 WAL，见实现处说明）。
        """
        ...

    async def close(self) -> None:
        """释放连接/连接池。

        ⚠️ 不关的后果：Postgres 连接池泄漏；Windows 上 SQLite 会锁住数据库文件，
        导致用户卸载/删除目录失败。
        """
        ...

    # ------------------------------------------------------------------
    # 读：取单个检查点
    # ------------------------------------------------------------------
    async def aget_tuple(self, config: Any) -> Any | None:
        """取出 `config` 指向的那份检查点。不存在返回 `None`。

        `config` 里必须有 `configurable.thread_id`（以及可选的
        `checkpoint_id` / `checkpoint_ns`）。

        ⚠️ 中断恢复依赖它：图暂停后，`astream` / `ainvoke` 要靠这里读回
        "停在哪、待处理的中断是什么"。
        """
        ...

    # ------------------------------------------------------------------
    # 读：列出一个 thread 的全部检查点
    # ------------------------------------------------------------------
    def alist(
        self,
        config: Any | None,
        *,
        filter: dict[str, Any] | None = None,
        before: Any | None = None,
        limit: int | None = None,
    ) -> AsyncIterator[Any]:
        """列出检查点（**注意：这不是 `async def`，返回的是异步迭代器**）。

        实测签名确认：上游第 443 行是 `async def alist(...)` 且内部 `yield`，
        即"异步生成器"。这里写成普通 `def` 返回 `AsyncIterator`，
        是为了在 Protocol 里表达清楚"它是可迭代的"。**实现处照上游写 `async def` + `yield` 即可。**
        """
        ...

    # ------------------------------------------------------------------
    # 写：存一份检查点
    # ------------------------------------------------------------------
    async def aput(
        self,
        config: Any,
        checkpoint: Any,
        metadata: Any,
        new_versions: Any,
    ) -> Any:
        """存入检查点，返回**更新后的 config**（含新生成的 `checkpoint_id`）。

        ⚠️ 返回值不能丢：调用方要用它把后续的 `aput_writes` 关联到这份检查点上。
        """
        ...

    # ------------------------------------------------------------------
    # 写：存该检查点下的中间写入
    # ------------------------------------------------------------------
    async def aput_writes(
        self,
        config: Any,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        """存入"某个任务产生的中间写入"。

        这些是**节点执行过程中的副作用记录**，用于中断恢复时知道
        "哪些节点的结果已经落过、不用重跑"。
        """
        ...

    # ------------------------------------------------------------------
    # 删：整条 thread
    # ------------------------------------------------------------------
    async def adelete_thread(self, thread_id: str) -> None:
        """删除一个 thread 的**全部**检查点与写入。

        ⚠️ 这是"删干净"的唯一入口。业务上 `DELETE /agent/threads/{id}` 必须走到这里——
        否则会留下孤儿数据（原实现就有这个问题，见 docs/PLAN.md 的验证清单
        「DELETE 后查 checkpoints 三表 0 残留」）。

        ⚠️ 幂等：删除不存在的 thread 不应报错（用户可能重复点删除）。
        """
        ...

"""
创建图的,以及连接大脑思维的——图的瓶装工厂函数

⚠️ 2026-09-11 重构：create_agent() + HumanInTheLoopMiddleware → 手搓 StateGraph（PLAN §十四）
   被换掉的那版（create_agent + middleware）为什么不行：
     ① 图结构固定（model ↔ tools 循环），加不了 §七 的自定义节点和条件边
     ② middleware 在 after_model 拦截，拿不到结构化 diff（只能塞进 description 字符串）
     ③ 黑盒 —— 出问题不知道去哪找

目标图结构（PLAN §七 + §十二 合并后的形态，**待你确认**）：

    START ─▶ [ 用户画像注入 ] ─▶ [ 意图路由 ] ─┬─(闲聊)───▶ [ LLM 生成(流式) ] ──┐
                                              ├─(需检索)─▶ [ RAG 检索 ] ────────┤
                                              └─(需工具)─▶ [ 子代理调度 ] ──────┤
                                                                                ▼
                                                                [ 持久化 ] ─▶ END
                                                     ▲
                                                     └── 循环回意图路由（多轮工具调用）

    ⚠️ 装配前先定：§七 的「LLM 生成」和 §十二 的「主管」是不是同一个东西？
       如果不是，子代理调度节点挂在哪一步？—— 这个不定，下面的装配写不下去
"""
from fastapi import Request
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import StateGraph, START, END
from langgraph.graph.state import CompiledStateGraph

from furina_desktop.agent.nodes.coder import coder_graph
from furina_desktop.agent.llm import llm
from furina_desktop.agent.state import SupervisorState


async def profile_node(state: SupervisorState):
    """用户画像注入（PLAN §七）

    TODO: [主管-1] 实现
      提示：顺带解决 PLAN §6 的缺口 —— 让 AI 认识用户（user_name / personal_preference）
      边界 1：数据从哪来？state 里带进来，还是这个节点去查库？
      边界 2：如果查库，节点就要拿 session —— 怎么传？
              （别把 ORM session 塞进 state，state 要能被序列化落 checkpoint）
    """
    raise NotImplementedError


async def route_node(state: SupervisorState):
    """意图路由（PLAN §七）

    TODO: [主管-2] 实现
      边界：原 PLAN 定的是「规则优先，LLM 兜底，默认闲聊」——
            「规则」具体判什么？关键词？还是 state["mode"] 直接决定？
    """
    raise NotImplementedError


def route_edge(state:SupervisorState) -> str:
    """条件边：决定走闲聊 / 检索 / 工具

    TODO: [主管-3] 实现
      返回字符串必须与 add_conditional_edges 映射表的 key 逐字一致
    """
    raise NotImplementedError


async def rag_node(state:SupervisorState):
    """RAG 检索（PLAN §七 / §二）

    TODO: [主管-4] 实现
      边界：设计上要调 Rust RAG 服务（/search，带 domain 参数）—— 但该服务还不存在
            MVP 阶段要不要先降级成占位实现，别让它阻塞整图跑通？
            （呼应你自己 9.10 立的规矩：最小可执行版，砍掉为「将来」做的抽象）
    """
    raise NotImplementedError


async def generate_node(state:SupervisorState):
    """LLM 生成（流式）

    TODO: [主管-5] 实现
      边界 1：按 state["mode"] 切换人设（roleplay / code）
      边界 2：流式输出要能对接现有 SSE —— 观测通道见 services/agent_stream.py
    """
    raise NotImplementedError


async def persist_node(state:SupervisorState):
    """持久化（PLAN §七）

    TODO: [主管-6] 实现
      提示：复用 repositories/message.py，别重新造
    """
    raise NotImplementedError


def build_graph(checkpointer: object) ->  CompiledStateGraph:
    """组装主管图

    TODO: [主管-7] 完成装配
      提示：这是**唯一**编译 checkpointer 的地方
            （PLAN §十四 / 9.11 验证手册 前提 2）
      边界：coder 子图以「节点」形式挂进来（路线 B）—— 见 node/coder.py
           挂节点 vs 挂编译好的子图，state schema 的对应关系要想清楚
    """
    builder =StateGraph(SupervisorState)
    builder.add_node("coder_graph",coder_graph)
    builder.add_edge(START,"coder_graph")
    builder.add_edge("coder_graph",END)
    # TODO: [主管-7] 在这里挂节点、接条件边、compile(checkpointer=...)
    supervisor= builder.compile(checkpointer = _unwrap_checkpointer(checkpointer))
    return supervisor


def _unwrap_checkpointer(obj: object):
    """把"适配器"解包成 LangGraph 认识的 saver。

    ⚠️ AI 新增（**只有真启动才发现这个坑**）。LangGraph 的
       `compile(checkpointer=...)` 会做类型检查，只认 `BaseCheckpointSaver`：

           Invalid checkpointer provided. Expected an instance of `BaseCheckpointSaver`,
           `True`, `False`, or `None`. Received SqliteCheckpointStore.

    而我们的架构是"业务代码依赖 `CheckpointStore` 协议，不依赖具体 saver"
    （见 `furina_core/checkpoint.py`）。两者不冲突，因为分工不同：

        业务层（routers / services）  → 依赖协议，可替换
        装配层（本函数）              → 交出真 saver

    判据：有 `.saver` 属性就取它，否则原样返回。
    好处：`build_graph` 既能收 `SqliteCheckpointStore`，也能收原生 saver ——
    测试时可以直接塞 `InMemorySaver`，不必造一个 SQLite 文件。
    """
    inner = getattr(obj, "saver", None)
    return inner if inner is not None else obj


# ══════════════════════════════════════════════════════════════════════
# 依赖注入：把编译好的图交给路由
# ══════════════════════════════════════════════════════════════════════
# ⚠️ AI 改动：这个函数**原来在 `storage/agent_graph.py`**，搬到了这里。
#
#    理由：它取的是"图"，属于**编排层**的注入点。
#    放在 storage/ 会让存储层反向依赖编排层（那边 import build_graph），
#    而且语义上也不对 —— 存储层凭什么提供"图"的依赖？
#
#    ⚠️ 它读的是 `app.state.graph`，而那个键**现在没有任何人写入** ——
#    原来在 `storage/agent_graph.py` 里赋值的那行被我移除了（因为它就是那条反向依赖）。
#    **M4 换存储时要补回写入点**，正确的位置是应用入口的 lifespan：
#
#        store = SqliteCheckpointStore(db_path)
#        await store.open()
#        app.state.checkpoint_store = store
#        app.state.graph = build_graph(store)      # ← 编排层组装，入口负责挂载
async def get_graph(request: Request) -> CompiledStateGraph:
    """依赖注入：返回编译好的主管图。

    `app.state.graph` 由应用入口的 lifespan 写入（见 `main.py`）——
    顺序是"先开 checkpoint store，再 build_graph，然后挂到 app.state"。
    """
    return request.app.state.graph

"""
创建图的,以及连接大脑思维的——图的瓶装工厂函数

⚠️ 2026-09-11 重构：create_agent() + HumanInTheLoopMiddleware → 手搓 StateGraph（PLAN §十四）
   被换掉的那版（create_agent + middleware）为什么不行：
     ① 图结构固定（model ↔ tools 循环），加不了 §七 的自定义节点和条件边
     ② middleware 在 after_model 拦截，拿不到结构化 diff（只能塞进 description 字符串）
     ③ 黑盒 —— 出问题不知道去哪找

Stage A 实际结构（2026-10-26 落地，取代上面那张旧规划图）：

    START ─▶ begin_turn_node ─▶ intent_node ─▶ validate_intent_node ─┬─(CHAT)───────────▶ chat_graph ─▶ END
                                      ▲                              ├─(CODE)───────────▶ coder_graph ─▶ END
                                      │                              └─(非法 / 不支持)──▶ route_failed_node ─▶ END
                                      └── 校验失败且未达上限：带 intent_error 回 intent_node

    · 条件边由 `validate_intent_node` 用 `Command(goto=...)` 给出，
      **不是** add_conditional_edges 的字符串映射表 —— 少一张会漂移的表。
    · 旧规划里的「用户画像 / RAG / 持久化」仍是占位（D-SUP-09 非目标），不装配。
"""
from fastapi import Request
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import StateGraph, START, END
from langgraph.graph.state import CompiledStateGraph

from furina_desktop.agent.nodes.chat import chat_graph
from furina_desktop.agent.nodes.coder import coder_graph
from furina_desktop.agent.nodes.supervisor import (
    begin_turn_node,
    intent_node,
    route_failed_node,
    validate_intent_node,
)
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


# [主管-2] / [主管-3] 已落地，位置变了：
#   意图路由的节点与落点映射在 `agent/nodes/supervisor.py`
#   （intent_node / validate_intent_node / route_failed_node）。
#   原来这里两个 `raise NotImplementedError` 的占位已删除 ——
#   留着会和真实现并存，读代码的人无法判断哪个才是权威。

async def rag_node(state:SupervisorState):
    """RAG 检索（PLAN §七 / §二）

    TODO: [主管-4] 实现
      边界：设计上要调 Rust RAG 服务（/search，带 domain 参数）—— 但该服务还不存在
            MVP 阶段要不要先降级成占位实现，别让它阻塞整图跑通？
            （呼应你自己 9.10 立的规矩：最小可执行版，砍掉为「将来」做的抽象）
    """
    raise NotImplementedError


async def generate_node(state:SupervisorState):
    """主管侧的 LLM 生成（占位，Stage A 未装配）。

    TODO: [主管-5] 实现
      · CHAT 的生成已经在 `nodes/chat.py` 里跑通（子图，不经本节点）；
        本节点留给 V2"主管需要多轮生成 / 汇总子图结果"的场景。
      · 原注释里的 `state["mode"]` 已删除（D-SUP-04），人设切换归子图管。
      边界 2：流式输出要能对接现有 SSE —— 观测通道见 agent/stream.py
    """
    raise NotImplementedError


async def persist_node(state:SupervisorState):
    """持久化（PLAN §七）

    TODO: [主管-6] 实现
      提示：复用 repositories/message.py，别重新造
    """
    raise NotImplementedError


def build_graph(checkpointer: object) ->  CompiledStateGraph:
    """组装主管图（Stage A）。

    这是**唯一**编译 checkpointer 的地方。子图以「编译好的图当节点」形式挂载
    （路线 B）：这样 namespace 里才有 `coder_graph:<id>` 前缀，SSE 归属、
    审批恢复预检（`runtime.preflight_resume` 深度遍历子图快照）才成立。

    ⚠️ 复核重点：
      1. 子图节点名（`coder_graph` / `chat_graph`）同时被 `agent/stream.py`
         的 `_AGENT_BY_NODE` 与 `nodes/supervisor.py` 的 `_GOTO` 引用 —— 改名要同步两处。
      2. `chat_graph` / `coder_graph` 的**输出字段**靠与 SupervisorState 同名映射回传
         （`result`）；不同名的字段（`coder_messages` / `chat_messages`）出不去子图。
    """
    builder = StateGraph(SupervisorState)

    # ── 主管自身的节点 ──
    # <- AI 改动（第二轮审计 D4）：轮次起点。每个 run 从 START 进来先清 run 级字段，
    #    重试边直接回 intent_node，不重复经过这里。理由见 nodes/supervisor.py 模块 docstring。
    builder.add_node("begin_turn_node", begin_turn_node)
    builder.add_node("intent_node", intent_node)
    builder.add_node("validate_intent_node", validate_intent_node)
    builder.add_node("route_failed_node", route_failed_node)

    # ── 子图 ──
    builder.add_node("chat_graph", chat_graph)
    builder.add_node("coder_graph", coder_graph)

    builder.add_edge(START, "begin_turn_node")
    builder.add_edge("begin_turn_node", "intent_node")
    builder.add_edge("intent_node", "validate_intent_node")
    # 校验节点的出口是 Command(goto=...)，因此这里没有 add_conditional_edges。
    builder.add_edge("chat_graph", END)
    builder.add_edge("coder_graph", END)
    builder.add_edge("route_failed_node", END)

    supervisor = builder.compile(checkpointer=_unwrap_checkpointer(checkpointer))
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

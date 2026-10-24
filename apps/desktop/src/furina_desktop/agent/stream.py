"""
作为 fastapi 和 Langgraph 的桥接层 —— 把图的输出流式呈递给用户

═══════════════════════════════════════════════════════════════════════
2026-10-24 实测结论（langgraph 1.2.11，真图 + 会流式的假模型）
═══════════════════════════════════════════════════════════════════════

  1. **必须开 `subgraphs=True`。** 否则只要本次 run 停在 interrupt，
     `messages` 流一个 token 都不吐 —— 模型节点产出的消息被压在子图里，
     要等 resume 时才以"整条消息"的形式重放出来（前端会看到重复内容）。
     开了 subgraphs 之后 chunk 变成三元组 `(namespace, mode, payload)`。

  2. **中断在 `payload["__interrupt__"]` 上**（updates 和 values 都有），
     子图与根图各发一次、**id 相同** → 必须按 id 去重。

  3. **归属在 namespace 里**：`('coder_graph:<uuid>',)`，node 名在 `:` 前，
     同一个 uuid 每次 run 都变，所以只能取前缀、不能硬编码。

  4. run 正常结束和"停在中断"都是正常返回；区别只能看
     `graph.aget_state(config).interrupts` —— 流本身不会抛异常。

⚠️ 不做的事：
  · 不迁 `stream_events(version="v3")`（experimental）
  · 不在挂起期间替用户"作废旧 pending"（TODO Q2 未拍板）—— 见 `agent_stream`
"""
import json
import logging
from typing import Any, AsyncIterator

from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command

from furina_desktop.agent.contracts import ReviewDecision
from furina_desktop.api.contracts import AgentRequest

logger = logging.getLogger(__name__)

# ── AI 改动：事件封闭集。前端只认这些 type，新增必须同步改前端。 ──
EVENT_TYPES = ("token", "tool_start", "tool_end", "approval_required", "error", "done")

# 一次 run 只要跨进子图，就带 namespace；空 namespace = 根图（主管）。
_AGENT_BY_NODE = {"coder_graph": "coder"}


class DecisionMismatch(Exception):
    """审批决定与待审项对不上（数量/ID/重复）。"""


def _sse(event: dict) -> str:
    if event["type"] not in EVENT_TYPES:
        raise ValueError(f"未登记的事件类型: {event['type']!r}")
    # ensure_ascii=False：中文直接落字节，省得前端再解一遍 \uXXXX
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


def _config(chat_thread_id: Any) -> dict:
    return {"configurable": {"thread_id": str(chat_thread_id)}}


def _agent_of(namespace: tuple[str, ...]) -> str:
    """从 namespace 推事件归属。`('coder_graph:uuid',)` → `coder`。"""
    if not namespace:
        return "supervisor"
    node = namespace[-1].split(":", 1)[0]
    return _AGENT_BY_NODE.get(node, node)


async def get_pending_tool_call_ids(*, graph: CompiledStateGraph, config: dict) -> list[str]:
    """读出当前挂起中断里所有待审的 tool_call_id（无挂起 → 空列表）。

    # ── AI 新增 ── 待人工复核
    # 复核重点：只认 `value["requests"]` 这个形状（ReviewRequest）。
    # 将来出现第二种审批载荷（shell 命令）时，这里要改成按 type 分派。
    """
    snapshot = await graph.aget_state(config)
    pending: list[str] = []
    for interrupt_obj in snapshot.interrupts:
        value = interrupt_obj.value if isinstance(interrupt_obj.value, dict) else {}
        for request in value.get("requests", []) or []:
            tool_call_id = request.get("tool_call_id")
            if tool_call_id:
                pending.append(tool_call_id)
    return pending


def check_decision_matches(decision: ReviewDecision, pending: list[str]) -> None:
    """逐条对齐校验：不多、不少、不重复。不满足直接抛 `DecisionMismatch`。

    # ── AI 新增 ── 待人工复核
    # 复核重点：这里用 set 比较，语义是"同一批"。如果将来要支持
    # "只批一部分、其余保持挂起"，这条判断就得改（TODO Q1 未拍板）。
    """
    decided = [item.tool_call_id for item in decision.decisions]
    if len(decided) != len(set(decided)):
        raise DecisionMismatch("审批决定里存在重复的 tool_call_id")
    if set(decided) != set(pending):
        raise DecisionMismatch(
            f"审批决定与待审项不匹配：待审 {sorted(pending)}，收到 {sorted(decided)}"
        )


async def _stream_graph(*, graph: CompiledStateGraph, graph_input: Any, config: dict) -> AsyncIterator[str]:
    """把一次图运行（首次或 resume）翻译成 SSE 帧。两条入口共用这一份分派逻辑。"""
    seen_interrupts: set[str] = set()
    started_tools: set[str] = set()
    ended_tools: set[str] = set()

    try:
        # ── AI 改动：subgraphs=True + 三模式。理由见模块 docstring 第 1、2 条。 ──
        async for namespace, mode, payload in graph.astream(
            graph_input,
            config=config,
            stream_mode=["messages", "updates", "values"],
            subgraphs=True,
        ):
            agent = _agent_of(namespace)

            if mode == "messages":
                message, _meta = payload
                if isinstance(message, ToolMessage):
                    tool_call_id = message.tool_call_id
                    if tool_call_id in ended_tools:
                        continue
                    ended_tools.add(tool_call_id)
                    yield _sse({
                        "type": "tool_end",
                        "agent": agent,
                        "id": tool_call_id,
                        "name": message.name,
                        "status": getattr(message, "status", None),
                        "content": str(message.content),
                    })
                elif isinstance(message, AIMessageChunk):
                    # 纯 token 流。空 chunk（工具调用结束时的收尾帧）不发给前端。
                    if isinstance(message.content, str) and message.content:
                        yield _sse({"type": "token", "agent": agent, "content": message.content})
                # 其余（HumanMessage / 完整 AIMessage）是回放或内部消息，不下发。

            elif mode == "updates":
                for node_name, update in payload.items():
                    if node_name == "__interrupt__":
                        for frame in _interrupt_frames(update, agent, seen_interrupts):
                            yield frame
                        continue
                    if not isinstance(update, dict):
                        continue
                    # 模型这一跳产出的 tool_calls → tool_start（参数必须完整，所以不从 chunk 拼）
                    for message in update.get("coder_messages", []) or []:
                        if not isinstance(message, AIMessage):
                            continue
                        for tool_call in message.tool_calls or []:
                            tool_call_id = tool_call.get("id")
                            if not tool_call_id or tool_call_id in started_tools:
                                continue
                            started_tools.add(tool_call_id)
                            yield _sse({
                                "type": "tool_start",
                                "agent": agent,
                                "id": tool_call_id,
                                "name": tool_call.get("name"),
                                "args": tool_call.get("args"),
                            })

            elif mode == "values":
                # 兜底：updates 里没接住的中断（理论上不会发生，id 去重保证不重复下发）
                interrupts = payload.get("__interrupt__")
                if interrupts:
                    for frame in _interrupt_frames(interrupts, agent, seen_interrupts):
                        yield frame

    except Exception as exc:  # noqa: BLE001 —— 错误必须以终态事件送达，而不是断流
        logger.exception("图运行失败")
        yield _sse({"type": "error", "code": "graph_error", "message": str(exc)})
        yield _sse({"type": "done", "status": "failed"})
        return

    # 正常返回有两种语义：跑完了 / 停在中断。只能问 checkpointer。
    snapshot = await graph.aget_state(config)
    if snapshot.interrupts:
        yield _sse({"type": "done", "status": "interrupted"})
    else:
        yield _sse({"type": "done", "status": "completed"})


def _interrupt_frames(interrupts, agent: str, seen: set[str]):
    """把中断对象翻译成 approval_required；同一 id 只发一次（子图/根图会各报一次）。"""
    for interrupt_obj in interrupts or ():
        interrupt_id = getattr(interrupt_obj, "id", None)
        if not interrupt_id or interrupt_id in seen:
            continue
        seen.add(interrupt_id)
        value = interrupt_obj.value if isinstance(interrupt_obj.value, dict) else {}
        yield _sse({
            "type": "approval_required",
            "agent": agent,
            "interrupt_id": interrupt_id,
            "review": value,
        })


async def agent_stream(*, inform: AgentRequest, graph: CompiledStateGraph) -> AsyncIterator[str]:
    """首次对话入口：用户输入 → 图 → SSE 帧。"""
    config = _config(inform.chat_thread_id)

    # ── AI 改动：挂起期间又发新消息的兜底。 ──
    # TODO Q2 还没拍板（409 vs 作废旧 pending），这里选**最保守**的一种：
    # 不启动新 run、不执行任何工具，只把"线程正挂着"告诉前端。
    # 复核重点：如果你更想要"新消息到达即作废旧审批"，改这里，别改 _stream_graph。
    pending = await get_pending_tool_call_ids(graph=graph, config=config)
    if pending:
        yield _sse({
            "type": "error",
            "code": "thread_suspended",
            "message": "该会话还有待审批的操作，请先批准或拒绝",
            "pending_tool_call_ids": pending,
        })
        yield _sse({"type": "done", "status": "interrupted"})
        return

    # ── AI 改动：显式给 mode / subagent_task（T3）。 ──
    # 目前主管图只挂了 coder 子图，所以 mode 固定 code；
    # 主管图的 route_node 接好后，这里应该从配置或请求里取。
    graph_input = {
        "messages": [{"role": "user", "content": inform.user_input}],
        "mode": "code",
        "subagent_task": inform.user_input,
    }
    async for frame in _stream_graph(graph=graph, graph_input=graph_input, config=config):
        yield frame


async def agent_resume_stream(
    *,
    graph: CompiledStateGraph,
    chat_thread_id: Any,
    decision: ReviewDecision,
) -> AsyncIterator[str]:
    """审批恢复入口：ReviewDecision → Command(resume=) → SSE 帧。

    # ── AI 新增 ── 待人工复核
    # 复核重点：路由层已经挡过一遍 409，这里再挡一次是为了**直接调用本函数**的
    # 测试/内部代码也不会把非法决定塞进图。两处判据必须保持一致。
    """
    config = _config(chat_thread_id)
    pending = await get_pending_tool_call_ids(graph=graph, config=config)

    if not pending:
        yield _sse({
            "type": "error",
            "code": "not_suspended",
            "message": "该会话当前没有待审批的操作",
        })
        yield _sse({"type": "done", "status": "completed"})
        return

    try:
        check_decision_matches(decision, pending)
    except DecisionMismatch as exc:
        yield _sse({"type": "error", "code": "decision_mismatch", "message": str(exc)})
        yield _sse({"type": "done", "status": "interrupted"})
        return

    # model_dump(mode="json")：ReviewAction 是 str 枚举，落盘/传输都要纯字符串
    async for frame in _stream_graph(
        graph=graph,
        graph_input=Command(resume=decision.model_dump(mode="json")),
        config=config,
    ):
        yield frame

"""
编程助手子代理 —— 手搓 ReAct 循环

    START ─▶ [ model ] ─▶ 条件边 ─┬─(有 tool_calls)─▶ [ tools ] ─┐
                ▲                 └─(无 tool_calls)─▶ END        │
                └────────────────────────────────────────────────┘

    注：tools 节点内部调用会改文件的工具时，工具自带 interrupt() → 图在此暂停
"""
from langchain_core.messages import AIMessage
from langgraph.types import Command,interrupt
from langgraph.prebuilt import ToolNode
from langchain.messages import HumanMessage,SystemMessage
from langgraph.graph import StateGraph,START,END
from langgraph.graph.state import CompiledStateGraph
from furina_desktop.agent.state import CoderState
from furina_desktop.agent.tools.registry import registry
from furina_desktop.agent.prompts.loader import aload_prompt
from furina_desktop.agent.llm import llm
from pydantic import ValidationError
from furina_desktop.agent.contracts import ReviewDecision, ReviewRequest
from furina_core.config import settings
from furina_desktop.agent.dependencies import build_write_review, build_tool_messages, classify_tool_calls, \
    handle_review_fn

coder_tools = registry.coder_tool
# 给模型绑定工具
llm_with_tools = llm.bind_tools(coder_tools)
SAFE_TOOLS   = registry.coder_safe_tools
RISKY_TOOLS = registry.coder_risky_tools

async def prepare_node(state: CoderState) -> dict:
    """
    把主管发来的任务转成子图的第一条消息
    :param state:子图的状态
    :return:更新字典
    """
    tool_tasks = state.subagent_task
    return {"coder_messages":[HumanMessage(tool_tasks)]}

async def model_node(state: CoderState):
    """
    调 LLM，产出 AIMessage（可能带 tool_calls）
    """
    # 读取提示词
    # ⚠️ AI 改动：原来是硬编码绝对路径 open("C:/furina-agent/backend/app/prompt/coder.txt")
    #    → 换机器/打包必炸。现在走 prompts/loader（路径基于 __file__ + 缓存 + 异步读）。
    # <- AI 改动：load_prompt → aload_prompt。
    #    load_prompt 是同步函数，返回 str；await str 会 TypeError。
    #    这个 bug 之前一直被 B1 挡着，够不到 model_node（阶段 1 未暴露）。
    prompt = await aload_prompt("coder")
    #拼接消息
    messages = [SystemMessage(prompt)] + state.coder_messages
    #调用大模型
    coder_messages = await llm_with_tools.ainvoke(messages)
    #更新消息字典
    return {"coder_messages": [coder_messages]}

#工具节点
#复用langgraph的工具节点
#注意，工具节点默认从messages字段取消息，而我的名称是coder_messages，所以得显示声明
tool_node = ToolNode(coder_tools,handle_tool_errors=True,messages_key="coder_messages")

#定义校验节点+预审批——放行全是安全工具的调用
# <- AI 改动：重写，并注册进图（原实现从未 add_node，见阶段 1 报告 B3）。
#   三条出口：未知工具→回填错误；全安全→tools_node；含高风险→review_node。
#   复核重点：未知工具按 fail-closed 处理，且会拦下**同批次的所有调用**
#   （因为一条 AI 消息里的 tool_calls 必须成组回填 ToolMessage）。
async def prevalidate_node(state: CoderState):
    #取出最新的消息看看是否有工具调用
    latest = state.coder_messages[-1]
    if not isinstance(latest,AIMessage) or not latest.tool_calls:
        return Command(goto="model_node")
    #原始工具调用
    raw_tool_calls = latest.tool_calls
    #分堆（按 name，不再对 dict 做 set）
    risky, safe, unknown = await classify_tool_calls(
        raw_tool_calls,
        RISKY_TOOLS,
        SAFE_TOOLS,
    )
    # 未知工具：整批拦下，回填错误消息让模型改
    if unknown:
        return Command(
            goto="model_node",
            update={
                "coder_messages": [
                    await build_tool_messages(
                        tc,
                        content=f"存在未知工具 {tc.get('name')}！请严格按照注册工具表调用工具"
                    )
                    for tc in raw_tool_calls
                ]
            }
        )
    # 全安全：直接走工具节点
    if not risky:
        return Command(goto="tools_node")
    # 含高风险：构造审批载荷
    risky_review = []
    try:
        for tool_detail in risky:
            tool_payload = await build_write_review(
                tool_call=tool_detail,
                workspace_root=settings.sandbox_root,
            )
            risky_review.append(tool_payload)
    except (ValueError, KeyError, OSError) as exc:
        # 载荷构造失败（越界/缺参/文件不可读）不能让图崩，回填错误让模型改
        return Command(
            goto="model_node",
            update={
                "coder_messages": [
                    await build_tool_messages(
                        tc,
                        content=f"审批载荷构造失败：{exc}"
                    )
                    for tc in raw_tool_calls
                ]
            }
        )
    payload = ReviewRequest(
        requests=risky_review
    )
    #更新状态，跳转到中断节点
    # <- AI 改动：存 dict 而不是 Pydantic 对象（理由见 state.py 同处注释）。
    return Command(
        goto="review_node",#前往中断节点
        update={
            "pending_reviews": payload.model_dump(mode="json")
        }
    )



async def review_node(state: CoderState)->Command:
    #读取快照的载荷，送审！
    snapshot = state.pending_reviews
    if snapshot is None:
        return Command(goto="model_node")
    #送审
    # <- AI 改动：resume 值原样交给 execute_node；字段名从 decision_review
    #    改成 decision_reviews（阶段 1 报告 B4，拼错会被 Pydantic 静默丢弃）。
    # snapshot 已经是 JSON 可序列化的 dict（prevalidate 时 model_dump 过）
    command_resume = interrupt(snapshot)
    return Command(
        goto="execute_node",#中断回复执行后跳转行节点
        update={
            "decision_reviews": command_resume #将人类审核结果存入状态
        }
    )


#定义执行节点
# <- AI 改动：原函数是空函数体且从未 add_node（阶段 1 报告 B5）。
#    现在只做校验与分发，真正的执行仍在 tools_node。
#    复核重点：这是阶段 2 的临时边界 —— 高风险工具此时仍会由 ToolNode 直接执行，
#    阶段 3 必须换成"统一执行器 + 数据库审批状态校验"（总案 §6）。
async def execute_node(state: CoderState)->Command:
    snapshot_raw = state.pending_reviews
    decision_raw = state.decision_reviews
    latest = state.coder_messages[-1]
    #快照或者决定为空时
    if not snapshot_raw or not decision_raw:
        return Command(goto="model_node")
    if not isinstance(latest, AIMessage) or not latest.tool_calls:
        return Command(goto="model_node")
    # <- AI 改动：state 里存的是 dict，这里才反序列化成契约对象。
    #    非法载荷一律 fail-closed，不执行任何工具。
    try:
        snapshot = ReviewRequest.model_validate(snapshot_raw)
        decision = ReviewDecision.model_validate(decision_raw)
    except ValidationError as exc:
        return Command(
            goto="model_node",
            update={
                "coder_messages": [
                    await build_tool_messages(
                        tc,
                        content=f"审批载荷非法，已阻止执行：{exc.errors()[:1]}"
                    )
                    for tc in latest.tool_calls
                ],
                "pending_reviews": None,
                "decision_reviews": None,
            },
        )
    return await handle_review_fn(
        decision=decision,
        snapshot=snapshot,
        raw_tool_calls=latest.tool_calls,
    )



def should_continue(state:CoderState) -> str:
    """
    条件边：判断回 model 还是结束
    """
    # <- AI 改动：有 tool_calls 时先去 prevalidate_node，不再直接送 review_node。
    #    原因：安全工具也必须被分类；直接送 review 会让全安全批次卡在审批门。
    #    用 getattr 是因为最后一条消息可能是 ToolMessage（没有 tool_calls 属性）。
    message = state.coder_messages[-1]
    if getattr(message, "tool_calls", None):
        return "prevalidate_node"
    else:
        return "END"


def build_coder(*,coder_prepare_node
                ,coder_model_node,
                coder_tools_node,
                coder_should_continue,
                coder_review_node,
                coder_prevalidate_node,
                coder_execute_node,
                ) ->CompiledStateGraph:
    """
    组装coder子图
    """
    builder = StateGraph(CoderState)
    #添加预节点
    builder.add_node("prepare_node",coder_prepare_node)
    #添加模型调用节点
    builder.add_node("model_node",coder_model_node)
    #添加工具调用节点
    builder.add_node("tools_node",coder_tools_node)
    #添加审核节点
    builder.add_node("review_node",coder_review_node)
    # <- AI 改动：注册 prevalidate_node 与 execute_node。
    #    原来这两个函数只有定义，没有节点，导致审批门不可达（B3/B5）。
    builder.add_node("prevalidate_node",coder_prevalidate_node)
    builder.add_node("execute_node",coder_execute_node)
    #添起始加边
    builder.add_edge(START,"prepare_node")
    #添加预构建节点到llm调用的边
    builder.add_edge("prepare_node","model_node")
    #构建llm调用到一个校验节点的边
    #添加条件边
    builder.add_conditional_edges(
        "model_node",
        coder_should_continue,
        {"prevalidate_node":"prevalidate_node","END":END}

    )
    #添加工具节点到llm节点的边
    builder.add_edge("tools_node","model_node")
    graph = builder.compile()
    return graph

coder_graph = build_coder(
    coder_prepare_node=prepare_node,
    coder_model_node=model_node,
    coder_tools_node=tool_node,
    coder_should_continue=should_continue,
    coder_review_node=review_node,
    coder_prevalidate_node=prevalidate_node,
    coder_execute_node=execute_node,
)
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
from furina_core.errors import InvalidToolError
from furina_desktop.agent.state import CoderState
from furina_desktop.agent.tools.registry import registry
from furina_desktop.agent.prompts.loader import load_prompt
from furina_desktop.agent.llm import llm
from furina_desktop.agent.contracts import ReviewAction, ReviewRequest
from furina_core.config import settings
from furina_desktop.agent.dependencies import build_write_review, build_tool_messages, classify_tool_calls, is_legal_args, \
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
    prompt = await load_prompt("coder")
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
async def prevalidate_node(state: CoderState):
    #取出最新的消息看看是否有工具调用
    latest = state.coder_messages[-1]
    if not isinstance(latest,AIMessage) or not latest.tool_calls:
        return Command(goto="model_node")
    #原始工具调用
    raw_tool_calls = latest.tool_calls
    #分堆
    try:
        risky,unknown = await classify_tool_calls(
            raw_tool_calls,
            RISKY_TOOLS,
            SAFE_TOOLS,
            registry=registry.coder_tool_name_registry

        )
    except InvalidToolError as e:
        pass
    #粗颗粒都审核——全安全和没有未知工具放行
    if not risky and not unknown:
        return Command(goto="model_node")
    # 如果有未知工具
    if unknown:
        return Command(
            goto="model_node",
            update={
                "coder_messages": [
                    await build_tool_messages(
                        tc,
                        content=f"存在位置工具{tc["name"]}！请严格按照注册工具工具表调用工具"
                        if tc in unknown else "存在未知工具，暂停执行"
                    )
                    for tc in raw_tool_calls
                ]
            }
        )
    #出现安全工具和危险工具并存——构造载荷并且存入快照，交给后面的中断节点
    risky_review = []  # 调用工具集合
    # 装填载荷
    for tool_detail in risky:
        tool_payload = await build_write_review(
            tool_call=tool_detail,
            workspace_root=settings.sandbox_root,
        )
        risky_review.append(tool_payload)
    payload = ReviewRequest(
        requests=risky_review
    )
    #更新状态，跳转到中断节点
    return Command(
        goto="review_node",#前往中断节点
        update={
            "pending_reviews": payload
        }
    )



async def review_node(state: CoderState)->Command:
    #读取快照的载荷，送审！
    snapshot = state.pending_reviews
    if snapshot is None:
        return Command(goto="model_node")
    #送审
    command_resume= interrupt(
        snapshot.model_dump(mode="json")
    )
    return Command(
        goto="execute_node",#中断回复执行后跳转行节点
        update={
            "decision_review":command_resume #将人类审核结果存入状态
        }
    )


#定义执行节点
async def execute_node(state: CoderState)->Command:
    snapshot = state.pending_reviews
    decision = state.decision_reviews
    #快照或者决定为空时
    if snapshot is None or decision is None:
        return Command(goto="model_node")



def should_continue(state:CoderState) -> str:
    """
    条件边：判断回 model 还是结束
    """
    message = state.coder_messages[-1]
    if message.tool_calls:
        return  "review_node"
    else:
        return "END"


def build_coder(*,coder_prepare_node
                ,coder_model_node,
                coder_tools_node,
                coder_should_continue,
                coder_review_node,
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
    #添起始加边
    builder.add_edge(START,"prepare_node")
    #添加预构建节点到llm调用的边
    builder.add_edge("prepare_node","model_node")
    #构建llm调用到review节点的边
    #添加条件边
    builder.add_conditional_edges(
        "model_node",
        coder_should_continue,
        {"review_node":"review_node","END":END}

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
)
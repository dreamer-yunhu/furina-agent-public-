"""
编程助手子代理 —— 手搓 ReAct 循环

    START ─▶ [ model ] ─▶ 条件边 ─┬─(有 tool_calls)─▶ [ tools ] ─┐
                ▲                 └─(无 tool_calls)─▶ END        │
                └────────────────────────────────────────────────┘

    注：tools 节点内部调用会改文件的工具时，工具自带 interrupt() → 图在此暂停
"""
from langgraph.types import Command,interrupt
from langgraph.prebuilt import ToolNode
from langchain.messages import HumanMessage,SystemMessage
from langgraph.graph import StateGraph,START,END
from langgraph.graph.state import CompiledStateGraph
from app.agent.state import CoderState
from app.agent.tools import bocha_search_tool
from app.agent.node.coder_tools import ReadFileTool, WriteFileTool
from app.agent.llm import llm
from app.schemas.model import ReviewDecision,ReviewRequest,WritePreview
from app.core.config import settings
read_file_tool = ReadFileTool()
write_file_tool = WriteFileTool()
coder_tools = [read_file_tool, write_file_tool,bocha_search_tool]

# 给模型绑定工具
llm_with_tools = llm.bind_tools(coder_tools)
#工具白名单
white_list = [read_file_tool.name]


async def prepare_node(state: CoderState) -> dict:
    """
    把主管发来的任务转成子图的第一条消息
    :param state:子图的状态
    :return:
    """
    tool_tasks = state.subagent_task
    return {"coder_messages":[HumanMessage(tool_tasks)]}

async def model_node(state: CoderState):
    """
    调 LLM，产出 AIMessage（可能带 tool_calls）
    """
    #读取提示词
    with open("C:/furina-agent/backend/app/prompt/coder.txt",
              "r",
              encoding="utf-8") as f:
        prompt = f.read()
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

async def review_node(state: CoderState):
    #取出最新的消息看看是否有工具调用需求
    latest = state.coder_messages[-1]
    #筛选出高危工具
    risky = [risky_tools
             for risky_tools in latest.tool_calls
             if risky_tools not in white_list
             ]
    tool_calls = []
    for tool_detail in latest.tool_calls:
        tool_payload = WritePreview(
            tool_call_id=tool_detail.get("id",None),
            path = tool_detail["args"]["file_path"],
            is_new_file =True,
            old_hash="str"

        )
        tool_calls.append(tool_payload)
    payload = ReviewRequest(
        requests=tool_calls
    )
    decision = interrupt(
        payload.model_dump(mode="json")
    )
    #返回出参数



def should_continue(state:CoderState) -> str:
    """
    条件边：判断回 model 还是结束
    """
    message = state.coder_messages[-1]
    if message.tool_calls:
        return  "tools_node"
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
    builder.add_edge("model_node","review_node")
    #添加条件边
    builder.add_conditional_edges(
        "review_node",
        coder_should_continue,
        {"tools_node":"tools_node","END":END}

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
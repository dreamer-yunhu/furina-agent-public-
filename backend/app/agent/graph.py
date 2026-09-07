"""
创建图的,以及连接大脑思维的
"""
from langgraph.graph import StateGraph, START,END
from langgraph.prebuilt import  tools_condition
from langgraph.checkpoint.base import BaseCheckpointSaver
from app.agent.node.chat import make_furina_node
from app.agent.state import State
from app.agent.tools import tool_node,tools
from app.agent.llm import llm

#定义蓝图函数
def build_graph(saver: BaseCheckpointSaver):
    #创建图
    graph_builder= StateGraph(State)
    #添加工具
    llm_with_tools=llm.bind_tools(tools)
    #添加节点
    #1——起点
    graph_builder.add_edge(START,"furina")
    #2——furina节点
    graph_builder.add_node("furina",make_furina_node(llm_with_tools))
    graph_builder.add_node("tools",tool_node)
    #添加条件边——什么时候进工具
    graph_builder.add_conditional_edges(
        "furina",
        tools_condition,
    )
    graph_builder.add_edge("tools", "furina")
    #3——终点
    graph_builder.add_edge("furina",END)
    #创建检查点

    return graph_builder.compile(checkpointer=saver)

# async def stream_graph_updates(user_input:ChatRequest):
#     messages = {"messages": [{"role": "user", "content": user_input.user_input}]}
#     async for event in graph.astream(messages,version="v2",stream_mode="messages"):
#          if event["type"] == "messages":
#             chunk,metadata = event["data"]
#             print(chunk.content, end="")



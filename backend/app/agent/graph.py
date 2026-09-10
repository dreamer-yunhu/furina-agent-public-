"""
创建图的,以及连接大脑思维的——图的瓶装工厂函数
"""
from langchain.agents import create_agent
from langgraph.checkpoint.base import BaseCheckpointSaver
from app.agent.llm import llm

#定义蓝图函数
def build_graph(saver: BaseCheckpointSaver,):
    supervisor = create_agent(
        model=llm,
        checkpointer=saver,
    )
    return supervisor


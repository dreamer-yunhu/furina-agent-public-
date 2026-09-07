"""
用于集成agent的聊天节点
"""
from app.agent.state import State
from langchain_openai import ChatOpenAI
def make_furina_node(llm:ChatOpenAI):
    async def furina_chat_node(state:State):
        """
        这个节点只负责一件事情——与模型交互
        :param state: langgraph的状态图
        :return:
        """
        response=await llm.ainvoke(state.messages)
        return {"messages":[response]}
    return furina_chat_node
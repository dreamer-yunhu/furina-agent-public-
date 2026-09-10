"""
定义编程助手节点
"""
from langchain.agents import create_agent
from langgraph.graph.state import CompiledStateGraph
from app.agent.llm import llm
from app.agent.node.coder_prompt import CODER_PROMPT
from app.agent.tools import bocha_search_tool
from app.agent.node.coder_tools import WriteFileTool,ReadFileTool
read_file_tool = ReadFileTool()
write_file_tool = WriteFileTool()
def build_coder()->CompiledStateGraph:
    coder = create_agent(
        model = llm,
        tools =[bocha_search_tool,read_file_tool,write_file_tool],
        system_prompt=CODER_PROMPT,
        name="coder",
    )
    return coder


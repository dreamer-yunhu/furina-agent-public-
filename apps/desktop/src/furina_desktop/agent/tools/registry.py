"""
工具注册表！！！
"""
from furina_desktop.agent.tools.coder_tools import ReadFileTool, WriteFileTool
from furina_desktop.agent.tools.builtin import bocha_search_tool


class ToolRegistry:
    def __init__(self,
                 coder_tool_name_registry : set[str],
                 coder_tool : list,
                 coder_safe_tools:set[str],
                 coder_risky_tools: set[str],
                 coder_tools_args : set[str],
                 comfyui_tool : list,
                 chatbot_tool : list):
        self.coder_tool_name_registry = coder_tool_name_registry
        self.coder_tool = coder_tool
        self.coder_safe_tools = coder_safe_tools
        self.coder_risky_tools = coder_risky_tools
        self.coder_tools_args = coder_tools_args
        self.comfyui_tool = comfyui_tool
        self.chatbot_tool = chatbot_tool

read_file_tool = ReadFileTool()
write_file_tool = WriteFileTool()

CODER_TOOLS= [read_file_tool, write_file_tool,bocha_search_tool]
CODER_TOOLS_NAME= {read_file_tool.name, write_file_tool.name, bocha_search_tool.name}
SAFE_TOOLS   = {read_file_tool.name, bocha_search_tool.name}   # 只读、无副作用
RISKY_TOOLS  = {write_file_tool.name}
CODER_TOOLS_AGRS = {arg for tool in CODER_TOOLS for arg in tool.args}
registry = ToolRegistry(
    coder_tool_name_registry= CODER_TOOLS_NAME,
    coder_tool= CODER_TOOLS,
    coder_safe_tools= SAFE_TOOLS,
    coder_risky_tools= RISKY_TOOLS,
    coder_tools_args= CODER_TOOLS_AGRS,
    comfyui_tool= [],
    chatbot_tool= []
)

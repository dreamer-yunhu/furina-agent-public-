"""
初始化llm
"""
from furina_core.config import settings
from langchain_openai import ChatOpenAI
llm = ChatOpenAI(
    model="deepseek-v4-flash",
    base_url=settings.base_url,
    api_key=settings.api_key,
)

# <- AI 新增（Stage A）：主管内部用的模型实例。
#    为什么必须单独一个：LangGraph 的 messages 流会挂 v2 流式回调，只要模型实现了
#    `_astream`（ChatOpenAI 实现了），**连 `ainvoke` 都会被改写成流式**，
#    意图识别的中间 token 就会漏到 SSE 上（D-SUP-08 / 报告 §R4，已实测）。
#    `disable_streaming=True` 是 langchain_core 里的硬关闭开关
#    （chat_models.py:525-547 `_streaming_disabled`），优先级高于任何流式触发。
#    复核重点：别把这里改成复用上面的 `llm` —— 那会让内部输出重新可流式。
supervisor_llm = ChatOpenAI(
    model="deepseek-v4-flash",
    base_url=settings.base_url,
    api_key=settings.api_key,
    disable_streaming=True,
)

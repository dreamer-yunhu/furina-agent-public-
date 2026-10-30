"""
初始化llm
"""
from furina_core.config import settings
from langchain_openai import ChatOpenAI

# <- AI 改动（T4 打包）：缺 key 不再让**导入**失败。
#    原写法 `api_key=settings.api_key` 在没配 .env 的机器上会让 ChatOpenAI
#    在模块导入期抛 OpenAIError，后端连 /healthz 都起不来 —— 用户看到的是
#    "未连接"，完全无法诊断。改用占位 key：进程能起、healthz 会报
#    llm_key_configured=false，真正的 401 推迟到调用模型时，经 SSE error 帧
#    回到界面。复核重点：这只是"可诊断"，不是"能用"——没有真 key 依然聊不了。
_UNSET_API_KEY = "not-configured"

llm = ChatOpenAI(
    model="deepseek-v4-flash",
    base_url=settings.base_url,
    api_key=settings.api_key or _UNSET_API_KEY,
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
    api_key=settings.api_key or _UNSET_API_KEY,
    disable_streaming=True,
)

"""CHAT 子图 —— 纯对话路径（Stage A 接入主管图）。

    START ─▶ prepare_node ─▶ model_node ─▶ END

与 coder 子图的分工：

    chat（本文件）   纯对话，**不挂工具**，不需要审批，没有 interrupt
    coder            读/写工具 + HITL 审批 + checkpoint 恢复

为什么是"子图"而不是挂在主管图上的一个节点（Stage A 已拍板）：
    1. 事件归属靠 namespace 判定（`stream._agent_of`），子图才有稳定前缀；
    2. 独立 `ChatState` 满足 D-SUP-05 —— 主管不需要看到 chat 的内部消息；
    3. 不会出现"所有子图都有 coder_messages"这种错误假设（D-SUP-08）。

契约（与主管的唯一接口）：
    输入  task_input  ← 主管同名映射
    输出  result      ← 同名映射回主管

⚠️ 现状：人设文件 `prompts/furina.txt` 仍是 0 字节。
   本阶段不接 RAG / Memory（D-SUP-09），只保证"能聊、能流式、能归位"。
"""

# ── AI-ASSISTED ── 本文件由 AI 生成/改写，待人工复核 ──
# 复核重点：
#   1. 我删掉了 `make_furina_node` 工厂，改成模块级 `chat_llm` —— 与 coder.py 的
#      `llm_with_tools` 保持一致（测试 monkeypatch 也沿用同一手法）。原来那个工厂
#      全项目无人调用。
#   2. `prepare_node` 每次都用 `task_input` 重新组消息，不读主管的 `messages`：
#      本阶段没有跨轮记忆（Memory Service 属非目标），别把它当成"忘了加历史"。
#   3. 人设为空时给了一句兜底 system prompt。M1 填好 furina.txt 后应删掉兜底。

from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from furina_desktop.agent.dependencies import message_text
from furina_desktop.agent.llm import llm
from furina_desktop.agent.prompts.loader import aload_prompt, available
from furina_desktop.agent.state import ChatState

# 测试注入点：与 coder_mod.llm_with_tools 同一手法（模块级变量，调用时读取）。
chat_llm = llm

_FALLBACK_PERSONA = "你是芙宁娜。用中文自然地回答，不要提到自己是语言模型。"


async def prepare_node(state: ChatState) -> dict:
    """组消息：人设（可选）+ 本次请求。

    TODO: [M1-1] 人设接 `knowledge/persona/`（32 文件 / 125 KB，目前无代码读取）
    """
    persona = (await aload_prompt("furina")).strip() if "furina.txt" in available() else ""
    messages: list = [SystemMessage(persona or _FALLBACK_PERSONA)]
    messages.append(HumanMessage((state.task_input or "").strip()))
    return {"chat_messages": messages}


async def model_node(state: ChatState) -> dict:
    """调用模型。

    ⚠️ 这里写的是 `ainvoke`，但 token 仍会流到 SSE —— LangGraph 挂了 v2 流式回调，
       ChatOpenAI 实现了 `_astream`，所以 `ainvoke` 内部会走流式桥（实测见
       docs/audit/2026-10-26-StageA-Phase0-核对报告.md §R4）。
       换句话说：**这里的 ainvoke 不影响流式**，别为了"要流式"去改写成 astream。
    """
    reply = await chat_llm.ainvoke(state.chat_messages)
    return {"chat_messages": [reply], "result": message_text(reply)}


def build_chat(*, prepare=prepare_node, model=model_node) -> CompiledStateGraph:
    builder = StateGraph(ChatState)
    builder.add_node("prepare_node", prepare)
    builder.add_node("model_node", model)
    builder.add_edge(START, "prepare_node")
    builder.add_edge("prepare_node", "model_node")
    builder.add_edge("model_node", END)
    return builder.compile()


chat_graph = build_chat()

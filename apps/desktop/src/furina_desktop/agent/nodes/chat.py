"""roleplay（闲聊）模式的节点 —— **当前未接入图**。

═══════════════════════════════════════════════════════════════════════
⚠️ 这个文件的状态：未接入 + 原来根本导不进来
═══════════════════════════════════════════════════════════════════════

**原来的问题**：它 `from furina_desktop.agent.state import State` —— 但 `state.py` 里
**没有 `State` 这个类**（只有 `SupervisorState` / `CoderState`）。
也就是说这个文件**从来就 import 不成功**，而且**全项目没有任何地方引用它**
（实测：只有它自己引用自己的函数名）。

**为什么保留而没有删掉**：它的逻辑对 **M1（芙宁娜可对话）** 直接相关 ——
它就是"主管图里的 LLM 生成节点"。删掉很容易，但 M1 时还得再写一遍。
所以这里把它**修成能 import 的样子**，并标清它离"能用"还差什么。

**修了什么**：`State` → `SupervisorState`（依据：原代码用 `state.messages`，两边都有该字段）。

**离能用还差什么**（M1 的活）：
    1. **人设注入**：现在把 `state.messages` 原样丢给模型，没有 system prompt。
       而人设的来源是：
         · `agent/prompts/furina.txt` —— **实测 0 字节，是空的**
         · `knowledge/persona/` —— 约 125 KB 语料，**没有任何代码读它**
       → M1 第一件事是填人设，第二件是接 RAG（M2）
    2. **用户画像**：`SupervisorState` 已有 `user_name` / `personal_preference` 字段
       （PLAN §6 的那个缺口），但**没有任何节点往里写**。本节点拼 prompt 时该用上。
    3. **流式输出**：现在是 `ainvoke`（一次性返回）。要流式得走 `astream`，
       而那属于 `agent/stream.py`（SSE 桥）的职责，不是节点内的事。
    4. **接进图**：`agent/build.py` 的 `build_graph` 现在只有
       `START → coder_graph → END`，**没有 roleplay 分支**。

═══════════════════════════════════════════════════════════════════════
它和 coder 的分工（双模式）
═══════════════════════════════════════════════════════════════════════

    roleplay（本文件）  纯对话，**不挂工具**，不需要审批
    code（coder 子图）  挂读/写工具，写操作进 HITL 审批

**两者的差别不只是 system prompt，是整套能力清单** —— 详见 docs/DESKTOP-PLAN.md §4.4。
"""

# ── AI-ASSISTED ── 本文件由 AI 生成/改写，待人工复核 ──
# 复核重点：
#   1. 我把 `State` 改成了 `SupervisorState` —— **这是推测性修复**，
#      依据是"原代码用 `state.messages`，而两个 state 都有该字段"。
#      请确认这个节点本来就该挂在**主管图**上（而不是别的图）。
#   2. 它仍然**未被接入任何图**，M1 才接。

from __future__ import annotations

from langchain_openai import ChatOpenAI

from furina_desktop.agent.state import SupervisorState


def make_furina_node(llm: ChatOpenAI):
    """工厂：把 llm 闭包进节点函数。

    ⚠️ 为什么用工厂而不是模块级单例：LangGraph 的节点函数**只能收 `state`**，
       所以依赖必须靠闭包注入。这与 `coder.py` 用模块级 `llm_with_tools`
       的做法不同 —— 两种都行，但闭包更容易测试（可以注入假 llm）。
    """

    async def furina_chat_node(state: SupervisorState):
        """这个节点只负责一件事 —— 与模型交互。

        TODO: [M1-1] 拼 system prompt（人设 + 用户画像）
        TODO: [M1-2] 按 `state.mode` 选能力清单（roleplay 不挂工具）
        """
        response = await llm.ainvoke(state.messages)
        return {"messages": [response]}

    return furina_chat_node

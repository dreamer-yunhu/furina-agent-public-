"""主管图的三个节点：意图识别 / 意图校验 / 路由失败落点。

    START ─▶ intent_node ─▶ validate_intent_node ─┬─(CHAT)────────▶ chat_graph ─▶ END
                    ▲                             ├─(CODE)────────▶ coder_graph ─▶ END
                    │                             └─(非法/不支持)─▶ route_failed_node ─▶ END
                    └── Command(goto="intent_node")  · 带着 intent_error 重试

为什么要拆成两个节点（D-SUP-02）：
    · 模型只负责"给出一个候选"，**合法值由程序定义**（`contracts.Intent`）；
    · 条件边只读校验后的 `intent`，绝不直接拿模型文本当路由指令；
    · 校验失败要能回到识别节点并且**有上限**，所以 `intent_attempts` 存在 state 里。

两类失败必须分开处理（D-SUP-02）：
    · 格式非法（不是 JSON / 缺字段 / 类型不对）→ 允许有限次重试；
    · 格式合法但意图不受支持（例如 "RAG"）→ **立即失败**，不重试 ——
      重试也只能得到同一个答案，属于无意义空转。

SSE 相关（D-SUP-08）：
    本文件的节点全部跑在**根图**里，namespace 为空。它们产生的 token 不得下发给用户，
    见 `stream._TOKEN_DENY_AGENTS`。此外 `intent_llm` 是 `disable_streaming=True` 的独立实例。
"""

# ── AI-ASSISTED ── 本文件由 AI 生成/改写，待人工复核 ──
# 复核重点：
#   1. `MAX_INTENT_ATTEMPTS = 2` 是拍的，不是算出来的 —— 超过两次基本说明提示词有问题。
#   2. `_GOTO` 映射是"意图 → 子图节点名"的**唯一**落点，新增意图必须同时改这里和 build.py。
#   3. `intent_node` 故意只喂"本次请求"而不喂整段对话历史：分类不需要上下文，
#      喂历史反而让"上一轮是代码、这一轮是寒暄"更容易误判。
#   4. `route_failed_node` 只写状态、不碰数据库 —— 生命周期迁移仍归 runtime（D-SUP-06）。

from __future__ import annotations

import json
import re

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.types import Command

from furina_desktop.agent.contracts import SUPPORTED_INTENTS, Intent
from furina_desktop.agent.dependencies import message_text
from furina_desktop.agent.llm import supervisor_llm
from furina_desktop.agent.prompts.loader import aload_prompt
from furina_desktop.agent.state import SupervisorState

MAX_INTENT_ATTEMPTS = 2
"""意图模型的调用上限（首次 + 1 次重试）。"""

_GOTO: dict[Intent, str] = {
    Intent.CHAT: "chat_graph",
    Intent.CODE: "coder_graph",
}

_FENCE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)

# 测试用注入点：沿用 `coder_mod.llm_with_tools` 的既有手法（模块级变量 + monkeypatch）。
intent_llm = supervisor_llm


async def intent_node(state: SupervisorState) -> dict:
    """调用模型产出意图候选。**只写 intent_raw，不写 intent。**

    复核重点：绝不把模型输出写进 `messages` —— 否则下一轮对话会把
    `{"intent":"CHAT"}` 当成用户/助手说过的话。
    """
    text = (state.task_input or "").strip()
    if not text:
        # 这是编程错误而不是用户错误：入口没按契约传 task_input。
        raise ValueError("主管图入口必须传 task_input（D-SUP-05）")

    messages = [SystemMessage(await aload_prompt("intent")), HumanMessage(text)]
    if state.intent_error:
        messages.append(
            HumanMessage(
                f"上一次输出不合法（{state.intent_error}）。"
                "请只输出一个 JSON 对象，不要任何额外文字。"
            )
        )

    reply = await intent_llm.ainvoke(messages)
    return {
        "intent_raw": message_text(reply),
        "intent_attempts": state.intent_attempts + 1,
    }


def validate_intent_node(state: SupervisorState) -> Command:
    """程序侧校验：结构 → 枚举值 → 落点。三个出口互斥。"""
    decision, format_error, unsupported = _parse_intent(state.intent_raw)

    if unsupported:
        # 合法 JSON、但是我们不支持的意图：立即失败，不做无意义重试。
        return Command(
            goto="route_failed_node",
            update={"intent": None, "route_error": unsupported},
        )

    if format_error:
        if state.intent_attempts >= MAX_INTENT_ATTEMPTS:
            return Command(
                goto="route_failed_node",
                update={
                    "intent": None,
                    "route_error": (
                        f"意图识别重试 {state.intent_attempts} 次仍不合法：{format_error}"
                    ),
                },
            )
        return Command(
            goto="intent_node",
            update={"intent_error": format_error, "intent_raw": None},
        )

    assert decision is not None  # noqa: S101 —— 三个出口互斥，走到这里必然有 decision
    update: dict = {
        "intent": decision.value,
        "intent_error": None,
        "route_status": "ok",
        "route_error": None,
    }
    if decision is Intent.CODE:
        # 显式映射：主管输入 → 子图输入（D-SUP-05）。
        # CHAT 不设这个字段：它自己的输入字段已经是 task_input，不需要中间名。
        update["subagent_task"] = state.task_input
    return Command(goto=_GOTO[decision], update=update)


def route_failed_node(state: SupervisorState) -> dict:
    """路由失败的唯一落点。

    复核重点：这里**只**写业务态。把 Task/Execution 迁到 FAILED 是运行时的事
    （`runtime.finalize_run` 读 `route_status`），节点里出现 session 就说明分层被破坏了。
    """
    return {"route_status": "failed"}


def _parse_intent(raw: str | None) -> tuple[Intent | None, str | None, str | None]:
    """解析模型输出。返回 `(意图, 格式错误, 不支持原因)`，三者互斥。

    ⚠️ 只容忍"整体被代码块包裹"这一种格式噪声（模型常见行为）。
       不做花括号搜索 —— 半截 JSON 被宽容拼接出来，会把真 bug 变成静默错误。
    """
    if not raw or not raw.strip():
        return None, "输出为空", None

    fenced = _FENCE.match(raw.strip())
    text = fenced.group(1) if fenced else raw.strip()

    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        return None, f"不是合法 JSON（{exc.msg}）", None

    if not isinstance(payload, dict):
        return None, "JSON 顶层不是对象", None

    raw_intent = payload.get("intent")
    if not isinstance(raw_intent, str) or not raw_intent.strip():
        return None, "缺少 intent 字段，或类型不是字符串", None

    value = raw_intent.strip().upper()
    if value not in SUPPORTED_INTENTS:
        return None, None, f"意图 {raw_intent!r} 不在当前版本支持范围 {sorted(SUPPORTED_INTENTS)}"

    return Intent(value), None, None

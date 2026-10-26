"""主管图的四个节点：轮次起点 / 意图识别 / 意图校验 / 路由失败落点。

    START ─▶ begin_turn_node ─▶ intent_node ─▶ validate_intent_node ─┬─(CHAT)────────▶ chat_graph ─▶ END
                                      ▲                              ├─(CODE)────────▶ coder_graph ─▶ END
                                      │                              └─(非法/不支持)─▶ route_failed_node ─▶ END
                                      └── Command(goto="intent_node")  · 带着 intent_error 重试

为什么要有 `begin_turn_node`（2026-10-26 第二轮审计修正 D1~D4）：
    LangGraph 把入口输入**合并**进已有 state。同一个 `graph_thread_id` 再跑一轮时，
    上一轮的 `intent_error` / `result` / `subagent_task` 会原样留在 state 里 ——
    其中 `intent_error` 会被 `intent_node` 当成"刚才那次失败"回填给模型
    （实测：新一轮第一次分类就被塞进一个不存在的前置失败前提）。
    之前只在入口重置 `intent_attempts` 一个字段，且这份重置散落在 3 个调用方，
    属于"修值"不"修结构"。现在把**轮次边界**收进图里：每个 run 从 START 进来
    先清一遍 run 级字段；重试边直达 `intent_node`、`Command(resume=...)` 从断点
    继续，两者都**不经过**本节点，所以重试与审批恢复的语义不变。
    ⚠️ 只清 run 级字段，**不动** `messages` / `task_id` / `execution_id` / `task_input`。

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
import logging
import re
from typing import NamedTuple

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.types import Command

from furina_desktop.agent.contracts import SUPPORTED_INTENTS, Intent
from furina_desktop.agent.dependencies import message_text
from furina_desktop.agent.llm import supervisor_llm
from furina_desktop.agent.prompts.loader import aload_prompt
from furina_desktop.agent.state import SupervisorState

logger = logging.getLogger(__name__)

MAX_INTENT_ATTEMPTS = 2
"""意图模型的调用上限（首次 + 1 次重试）。"""

_GOTO: dict[Intent, str] = {
    Intent.CHAT: "chat_graph",
    Intent.CODE: "coder_graph",
}

_FENCE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)

# 测试用注入点：沿用 `coder_mod.llm_with_tools` 的既有手法（模块级变量 + monkeypatch）。
intent_llm = supervisor_llm

# ── AI 新增（第二轮审计 D1~D4）：只在**轮次边界**清空的字段 ──
# 判据：这些字段描述"这一次 run 的结论"，跨 run 携带一定是错的。
# ⚠️ 不要往里加 messages / task_input / task_id / execution_id ——
#    它们要么是历史（messages），要么由入口每轮重新提供。
_RUN_SCOPED_NULLABLE = (
    "intent",
    "intent_raw",
    "intent_reason",
    "intent_error",
    "route_status",
    "route_error",
    "result",
    "subagent_task",
)


async def begin_turn_node(state: SupervisorState) -> dict:
    """轮次起点：把上一轮残留的运行期字段重置。

    # ── AI 新增 ── 待人工复核
    复核重点：
      1. 这个节点**只**清 run 级字段。清 `messages` 会删掉主管的对话历史，
         那是另一种伤害，别为了"干净"顺手加上。
      2. `intent_attempts` 单独写 0 —— 上面那张表里放 None 会撞 Pydantic 的 int 校验。
      3. 重试边是 `Command(goto="intent_node")`，**绕开本节点**；
         审批恢复是 `Command(resume=...)`，也从断点继续。两者都不受影响。
    """
    update: dict = {name: None for name in _RUN_SCOPED_NULLABLE}
    update["intent_attempts"] = 0
    return update


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


def _with_reason(error: str, reason: str | None) -> str:
    """把模型的 `reason` 拼进**给人看**的错误文案。

    # ── AI 新增（第二轮审计·`reason` 上线）── 待人工复核
    复核重点：它**只影响文案**，不参与任何判断；`reason` 为空时原样返回。
      不要用它去拼 `intent_raw` / `messages` —— 那会把模型输出混进对话。
      文案最终经 `stream._stream_graph` 的 `route_error` 送到前端，
      所以长度要克制：`reason` 已在解析处截断到 255。
    """
    if not reason:
        return error
    return f"{error}（模型理由：{reason}）"


def validate_intent_node(state: SupervisorState) -> Command:
    """程序侧校验：结构 → 枚举值 → 落点。三个出口互斥。"""
    parsed = _parse_intent(state.intent_raw)

    if parsed.unsupported:
        # 合法 JSON、但是我们不支持的意图：立即失败，不做无意义重试。
        # reason 一并落进 state 与错误文案 —— 路由失败时"模型为什么这么选"最有用。
        return Command(
            goto="route_failed_node",
            update={
                "intent": None,
                "intent_reason": parsed.reason,
                "route_error": _with_reason(parsed.unsupported, parsed.reason),
            },
        )

    if parsed.format_error:
        if state.intent_attempts >= MAX_INTENT_ATTEMPTS:
            return Command(
                goto="route_failed_node",
                update={
                    "intent": None,
                    # 最后一跳可能仍是"合法 JSON 但缺 intent 字段"，此时 reason 是有值的
                    "intent_reason": parsed.reason,
                    "route_error": _with_reason(
                        f"意图识别重试 {state.intent_attempts} 次仍不合法：{parsed.format_error}",
                        parsed.reason,
                    ),
                },
            )
        return Command(
            goto="intent_node",
            update={"intent_error": parsed.format_error, "intent_raw": None},
        )

    decision = parsed.intent
    assert decision is not None  # noqa: S101 —— 三个出口互斥，走到这里必然有 decision
    # <- AI 改动（`reason` 上线）：成功路由也留一条可检索的痕迹。
    #    checkpoint 里有 intent_raw，但没人会去翻 SQLite；日志是排查时的第一落点。
    logger.info("意图路由 intent=%s reason=%s", decision.value, parsed.reason)
    update: dict = {
        "intent": decision.value,
        # <- AI 改动（第二轮审计拍板）：reason 只是**留档 + 排查线索**，不参与任何判断。
        "intent_reason": parsed.reason,
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


class ParsedIntent(NamedTuple):
    """`_parse_intent` 的返回值。

    # ── AI 新增（第二轮审计拍板）── 待人工复核
    为什么不用 4 元组：`(intent, reason, format_error, unsupported)` 里有两个
    相邻的"错误原因"，位置一写反就是静默错误 —— 具名比位置可靠。
    复核重点：`intent` 为 None 时，`format_error` / `unsupported` **必有且仅有一个**为真。
    """

    intent: Intent | None
    reason: str | None
    format_error: str | None
    unsupported: str | None


# `reason` 只做留档：缺失/空串/类型不对一律 None，超长截断。
# 上限与 `SupervisorState.intent_reason` 的 max_length 对齐 ——
# 不在解析处截断的话，模型偶尔写长一句就会撞 Pydantic 校验，让整张图报错。
_MAX_REASON_CHARS = 255


def _clean_reason(payload: dict) -> str | None:
    """取出 `reason` 并归一化。**永不抛异常、永不阻塞路由。**"""
    reason = payload.get("reason")
    if not isinstance(reason, str):
        return None
    return reason.strip()[:_MAX_REASON_CHARS] or None


def _parse_intent(raw: str | None) -> ParsedIntent:
    """解析模型输出。`intent` 至多一个出口为真，`reason` 只是附带信息。

    ⚠️ 只容忍"整体被代码块包裹"这一种格式噪声（模型常见行为）。
       不做花括号搜索 —— 半截 JSON 被宽容拼接出来，会把真 bug 变成静默错误。
    """
    if not raw or not raw.strip():
        return ParsedIntent(None, None, "输出为空", None)

    fenced = _FENCE.match(raw.strip())
    text = fenced.group(1) if fenced else raw.strip()

    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        return ParsedIntent(None, None, f"不是合法 JSON（{exc.msg}）", None)

    if not isinstance(payload, dict):
        return ParsedIntent(None, None, "JSON 顶层不是对象", None)

    reason = _clean_reason(payload)
    raw_intent = payload.get("intent")
    if not isinstance(raw_intent, str) or not raw_intent.strip():
        return ParsedIntent(None, reason, "缺少 intent 字段，或类型不是字符串", None)

    value = raw_intent.strip().upper()
    if value not in SUPPORTED_INTENTS:
        return ParsedIntent(
            None,
            reason,
            None,
            f"意图 {raw_intent!r} 不在当前版本支持范围 {sorted(SUPPORTED_INTENTS)}",
        )

    return ParsedIntent(Intent(value), reason, None, None)

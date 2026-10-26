"""Stage A · 第二轮审计回归：同一 graph_thread_id 的跨轮状态残留。

# ── AI-ASSISTED ── 本文件由 AI 生成，待人工复核 ──
# 类型：真 LangGraph + 真子图 + 假模型；断言看**每轮结束后的最终状态**。
# 背景：`begin_turn_node` 是 2026-10-26 第二轮审计的修正（D1~D4）——
#   之前只在入口重置 `intent_attempts`，于是同一 thread 再跑一轮时：
#     D1 `intent_error` 会把"上一次输出不合法"喂进新一轮的第一次分类；
#     D2 `result` 会保留上一轮的业务结果（失败轮 route_status=failed 却 result 非空）；
#     D3 `subagent_task` 会保留上一轮 CODE 的任务文本。
# 复核重点：这里断言的是"上一轮的字段不该出现在这一轮"，不是节点返回值。
#   如果哪天 `begin_turn_node` 被从 build.py 摘掉，本文件的 1/2/3/4 会先红。

跑法（仓库根）：
    .venv-build\\Scripts\\python.exe apps\\desktop\\tests\\smoke_supervisor_turns.py

覆盖：
    1. CHAT 成功 → 意图失败：result / subagent_task 不得残留
    2. 意图失败 → 成功：新一轮第一次分类不得带上一轮的失败反馈
    3. CODE 成功 → CHAT 成功：subagent_task 必须清空
    4. CODE 成功 → 意图失败：result 必须清空
    5. 重试预算按轮重置：上一轮用满 2 次，本轮仍可用满 2 次
    6. messages 跨轮保留（begin_turn_node 不许清历史）
    7. intent_reason 也属于 run 级字段：新一轮没有 reason 时必须回 None
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "apps" / "desktop" / "src"))
sys.path.insert(0, str(ROOT / "packages" / "core" / "src"))

from langchain_core.messages import AIMessage, HumanMessage  # noqa: E402
from langgraph.checkpoint.memory import InMemorySaver  # noqa: E402

import furina_desktop.agent.nodes.chat as chat_mod  # noqa: E402
import furina_desktop.agent.nodes.coder as coder_mod  # noqa: E402
from furina_desktop.agent.build import build_graph  # noqa: E402
from _t23_testkit import install_intent  # noqa: E402

PASS, FAIL = "PASS", "FAIL"
_results: list[tuple[str, bool]] = []


def check(label: str, ok: bool, extra: str = "") -> None:
    _results.append((label, ok))
    print(f"  [{PASS if ok else FAIL}] {label}" + (f"   {extra}" if extra else ""))


class FakeModel:
    """只要能 ainvoke 就行 —— 节点只看返回值。"""

    def __init__(self, text: str) -> None:
        self.text = text
        self.calls = 0

    async def ainvoke(self, messages):
        self.calls += 1
        return AIMessage(content=self.text)


async def run_case(graph, thread: str, text: str) -> dict:
    """模拟生产入口：只给 messages + task_input（不再手工重置任何计数）。"""
    config = {"configurable": {"thread_id": thread}}
    await graph.ainvoke(
        {"messages": [HumanMessage(content=text)], "task_input": text},
        config,
    )
    return (await graph.aget_state(config)).values


async def main() -> None:
    graph = build_graph(InMemorySaver())

    # ═══ 1. CHAT 成功 → 意图失败 ═══
    print("=== 1. CHAT 成功 → 意图失败（同 thread）===")
    th = "turns-chat-then-fail"
    install_intent("CHAT")
    chat_mod.chat_llm = FakeModel("你好呀")
    state = await run_case(graph, th, "今天好累")
    check("round1 result present", state.get("result") == "你好呀", str(state.get("result")))

    install_intent(script=["我不会输出 JSON", "还是不会"])
    state = await run_case(graph, th, "随便说点什么")
    check("round2 route_status=failed", state.get("route_status") == "failed",
          str(state.get("route_status")))
    check("round2 intent=None", state.get("intent") is None, str(state.get("intent")))
    check("round2 result NOT carried over", state.get("result") is None,
          f"result={state.get('result')!r}")
    check("round2 subagent_task NOT carried over", state.get("subagent_task") is None,
          str(state.get("subagent_task")))

    # ═══ 2. 意图失败 → 成功 ═══
    print("\n=== 2. 意图失败 → 成功（同 thread）===")
    th = "turns-fail-then-ok"
    install_intent(script=["不是 JSON", "还没有 JSON"])
    state = await run_case(graph, th, "第一句")
    check("round1 exhausted retries", state.get("intent_attempts") == 2,
          str(state.get("intent_attempts")))
    check("round1 intent_error recorded", bool(state.get("intent_error")),
          str(state.get("intent_error")))

    fake = install_intent("CHAT")
    state = await run_case(graph, th, "第二句")
    check("round2 intent=CHAT", state.get("intent") == "CHAT", str(state.get("intent")))
    check("round2 route_status=ok", state.get("route_status") == "ok",
          str(state.get("route_status")))
    check("round2 intent_error cleared", state.get("intent_error") is None,
          str(state.get("intent_error")))
    check("round2 attempts starts from 1", state.get("intent_attempts") == 1,
          str(state.get("intent_attempts")))
    first_call = fake.inputs[0] if fake.inputs else []
    # D1 的核心断言：新一轮第一次分类不得收到上一轮的失败反馈。
    # ⚠️ 只看 HumanMessage —— 提示词本身就有"如果收到'上一次输出不合法'的提示…"这句话，
    #    把 SystemMessage 也扫进来会假红（本轮实测踩过）。
    first_humans = [str(getattr(m, "content", "")) for m in first_call
                    if isinstance(m, HumanMessage)]
    check("round2 first call has no stale feedback",
          not any("上一次输出不合法" in text for text in first_humans),
          str(first_humans))
    check("round2 first call has exactly one human message",
          sum(1 for m in first_call if isinstance(m, HumanMessage)) == 1,
          str([getattr(m, "content", "") for m in first_call]))

    # ═══ 3. CODE 成功 → CHAT 成功 ═══
    print("\n=== 3. CODE 成功 → CHAT 成功（同 thread）===")
    th = "turns-code-then-chat"
    install_intent("CODE")
    coder_mod.llm_with_tools = FakeModel("改写完成")
    state = await run_case(graph, th, "把 readme 改成 hello")
    check("round1 subagent_task mapped", state.get("subagent_task") == "把 readme 改成 hello",
          str(state.get("subagent_task")))

    install_intent("CHAT")
    chat_mod.chat_llm = FakeModel("嗨，我在")
    state = await run_case(graph, th, "陪我聊聊")
    check("round2 intent=CHAT", state.get("intent") == "CHAT", str(state.get("intent")))
    check("round2 result from chat", state.get("result") == "嗨，我在", str(state.get("result")))
    check("round2 subagent_task cleared", state.get("subagent_task") is None,
          str(state.get("subagent_task")))

    # ═══ 4. CODE 成功 → 意图失败 ═══
    print("\n=== 4. CODE 成功 → 意图失败（同 thread）===")
    th = "turns-code-then-fail"
    install_intent("CODE")
    coder_mod.llm_with_tools = FakeModel("改好了")
    state = await run_case(graph, th, "改个配置")
    check("round1 result present", state.get("result") == "改好了", str(state.get("result")))
    install_intent(script=["RAG 不支持的那个", "还是文本"])
    state = await run_case(graph, th, "换个人说话")
    check("round2 route_status=failed", state.get("route_status") == "failed",
          str(state.get("route_status")))
    check("round2 result cleared", state.get("result") is None, f"result={state.get('result')!r}")
    check("round2 subagent_task cleared", state.get("subagent_task") is None,
          str(state.get("subagent_task")))

    # ═══ 5. 重试预算按轮重置 ═══
    print("\n=== 5. 重试预算按轮重置 ===")
    th = "turns-retry-budget"
    install_intent(script=["坏输出", "还是坏输出"])
    state = await run_case(graph, th, "第一轮")
    check("round1 used 2 attempts", state.get("intent_attempts") == 2,
          str(state.get("intent_attempts")))

    fake = install_intent(script=["坏输出", json.dumps({"intent": "CHAT"})])
    chat_mod.chat_llm = FakeModel("第二次才对")
    state = await run_case(graph, th, "第二轮")
    check("round2 could retry once", fake.calls == 2, f"n={fake.calls}")
    check("round2 attempts == 2 (not 3/4)", state.get("intent_attempts") == 2,
          str(state.get("intent_attempts")))
    check("round2 routed", state.get("intent") == "CHAT", str(state.get("intent")))
    second_call = fake.inputs[1] if len(fake.inputs) > 1 else []
    check("same-round feedback still works",
          any("上一次输出不合法" in str(getattr(m, "content", "")) for m in second_call),
          str([getattr(m, "content", "") for m in second_call]))

    # ═══ 6. messages 跨轮保留 ═══
    print("\n=== 6. messages 跨轮保留（begin_turn_node 不许清历史）===")
    th = "turns-messages"
    install_intent("CHAT")
    chat_mod.chat_llm = FakeModel("嗯")
    await run_case(graph, th, "第一句")
    state = await run_case(graph, th, "第二句")
    check("supervisor messages kept", len(state.get("messages") or []) == 2,
          f"n={len(state.get('messages') or [])}")

    # ═══ 7. intent_reason 随轮清空 ═══
    print("\n=== 7. intent_reason 随轮清空 ===")
    th = "turns-reason"
    install_intent(script=[json.dumps({"intent": "CHAT", "reason": "第一轮的理由"})])
    chat_mod.chat_llm = FakeModel("嗯")
    state = await run_case(graph, th, "第一句")
    check("round1 reason recorded", state.get("intent_reason") == "第一轮的理由",
          str(state.get("intent_reason")))

    install_intent(script=[json.dumps({"intent": "CHAT"})])
    state = await run_case(graph, th, "第二句")
    check("round2 reason reset (no carry-over)", state.get("intent_reason") is None,
          str(state.get("intent_reason")))

    ok = sum(1 for _, o in _results if o)
    print(f"\n{ok}/{len(_results)} passed")
    if ok != len(_results):
        print("failed:")
        for label, o in _results:
            if not o:
                print("  -", label)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())

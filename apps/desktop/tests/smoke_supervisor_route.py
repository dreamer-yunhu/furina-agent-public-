"""Stage A · Phase 1 冒烟：主管图 CHAT / CODE 路由闭环。

# ── AI-ASSISTED ── 本文件由 AI 生成，待人工复核 ──
# 类型：真 LangGraph + 真子图 + 假模型（意图 / chat / coder 三处都是替身）。
# 断言看的是**图跑完后的最终状态**，不是中途某个节点返回了什么。
# 复核重点：
#   1. 这里不联网，也不建 Task/Execution（那是 Phase 3/4 的用例）。
#   2. "非法意图不会落进 coder" 是本文件的核心断言，别改成只看 route_status。

跑法（仓库根）：
    .venv-build\\Scripts\\python.exe apps\\desktop\\tests\\smoke_supervisor_route.py

覆盖：
    1. CHAT 走 chat 子图，result 有值，主管 messages 不被污染
    2. CODE 走 coder 子图，result 有值，subagent_task 由图从 task_input 映射而来
    3. 输出格式非法 → 重试一次仍非法 → route_status=failed（不进任何子图）
    4. 首次非法、第二次合法 → 正常路由，intent_attempts=2
    5. 格式合法但意图不受支持（RAG）→ 立即失败，**不重试**
    6. 状态契约：chat / coder / supervisor 三份 State 的字段边界
    7. `intent_reason`：能落盘、缺失/类型错不阻塞路由、超长截断；
       失败时并入 route_error 文案（用户可见），成功路由写一条 intent/reason 日志
"""

from __future__ import annotations

import asyncio
import json
import logging
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
        self.inputs: list[list] = []

    async def ainvoke(self, messages):
        self.calls += 1
        self.inputs.append(list(messages))
        return AIMessage(content=self.text)


async def run_case(graph, thread: str, text: str) -> dict:
    config = {"configurable": {"thread_id": thread}}
    await graph.ainvoke(
        {"messages": [HumanMessage(content=text)], "task_input": text},
        config,
    )
    return (await graph.aget_state(config)).values


async def main() -> None:
    graph = build_graph(InMemorySaver())

    # ═══ 1. CHAT ═══
    print("=== 1. intent=CHAT → chat 子图 ===")
    install_intent("CHAT")
    chat_mod.chat_llm = FakeModel("你好呀，我是芙宁娜。")
    coder_mod.llm_with_tools = FakeModel("不该被调用")
    state = await run_case(graph, "route-chat", "今天有点累")
    check("intent=CHAT", state.get("intent") == "CHAT", str(state.get("intent")))
    check("route_status=ok", state.get("route_status") == "ok", str(state.get("route_status")))
    check("result from chat", state.get("result") == "你好呀，我是芙宁娜。", str(state.get("result")))
    check("chat model called once", chat_mod.chat_llm.calls == 1, f"n={chat_mod.chat_llm.calls}")
    check("coder model untouched", coder_mod.llm_with_tools.calls == 0,
          f"n={coder_mod.llm_with_tools.calls}")
    # D-SUP-05：chat 的内部消息不能回流到主管
    check("supervisor messages not polluted", len(state.get("messages") or []) == 1,
          f"n={len(state.get('messages') or [])}")

    # ═══ 2. CODE ═══
    print("\n=== 2. intent=CODE → coder 子图 ===")
    install_intent("CODE")
    coder_mod.llm_with_tools = FakeModel("改写完成")
    state = await run_case(graph, "route-code", "把 readme 改成 hello")
    check("intent=CODE", state.get("intent") == "CODE", str(state.get("intent")))
    check("route_status=ok", state.get("route_status") == "ok", str(state.get("route_status")))
    check("result from coder", state.get("result") == "改写完成", str(state.get("result")))
    check("subagent_task mapped from task_input",
          state.get("subagent_task") == "把 readme 改成 hello", str(state.get("subagent_task")))
    check("coder model called once", coder_mod.llm_with_tools.calls == 1,
          f"n={coder_mod.llm_with_tools.calls}")

    # ═══ 3. 格式非法 → 重试耗尽 ═══
    print("\n=== 3. 非法输出 → 重试耗尽 → 失败 ===")
    intent_fake = install_intent(script=["我不会输出 JSON", "还是不会"])
    chat_mod.chat_llm = FakeModel("不该被调用")
    coder_mod.llm_with_tools = FakeModel("不该被调用")
    state = await run_case(graph, "route-bad", "随便说点什么")
    check("intent model retried", intent_fake.calls == 2, f"n={intent_fake.calls}")
    check("route_status=failed", state.get("route_status") == "failed", str(state.get("route_status")))
    check("intent stays None", state.get("intent") is None, str(state.get("intent")))
    check("route_error mentions retries", "重试" in (state.get("route_error") or ""),
          str(state.get("route_error")))
    check("no subgraph executed", chat_mod.chat_llm.calls == 0
          and coder_mod.llm_with_tools.calls == 0,
          f"chat={chat_mod.chat_llm.calls} coder={coder_mod.llm_with_tools.calls}")
    check("result is None", state.get("result") is None, str(state.get("result")))

    # ═══ 4. 一次非法后转合法 ═══
    print("\n=== 4. 首次非法 → 重试成功 ===")
    intent_fake = install_intent(script=["不是 json", json.dumps({"intent": "CHAT"})])
    chat_mod.chat_llm = FakeModel("第二次就对了")
    state = await run_case(graph, "route-retry", "在吗")
    check("retried once", intent_fake.calls == 2, f"n={intent_fake.calls}")
    check("intent=CHAT", state.get("intent") == "CHAT", str(state.get("intent")))
    check("intent_attempts=2", state.get("intent_attempts") == 2, str(state.get("intent_attempts")))
    check("route_status=ok", state.get("route_status") == "ok", str(state.get("route_status")))
    check("result present", state.get("result") == "第二次就对了", str(state.get("result")))
    # 重试时必须把失败原因回填给模型（D-SUP-02）
    second_call = intent_fake.inputs[1] if len(intent_fake.inputs) > 1 else []
    check("feedback returned to model",
          any("不合法" in str(getattr(m, "content", "")) for m in second_call),
          str([getattr(m, "content", "") for m in second_call]))

    # ═══ 5. 合法但不支持 ═══
    print("\n=== 5. 合法但不支持（RAG）→ 立即失败，不重试 ===")
    intent_fake = install_intent(script=[json.dumps({"intent": "RAG"})])
    coder_mod.llm_with_tools = FakeModel("不该被调用")
    state = await run_case(graph, "route-unsupported", "查一下资料")
    check("no retry", intent_fake.calls == 1, f"n={intent_fake.calls}")
    check("route_status=failed", state.get("route_status") == "failed", str(state.get("route_status")))
    check("error says unsupported", "不在当前版本支持范围" in (state.get("route_error") or ""),
          str(state.get("route_error")))
    check("did not fall back to coder", coder_mod.llm_with_tools.calls == 0,
          f"n={coder_mod.llm_with_tools.calls}")

    # ═══ 6. 契约边界（D-SUP-05）：子图字段不得互相冒充 ═══
    print("\n=== 6. 状态契约 ===")
    from furina_desktop.agent.state import ChatState, CoderState, SupervisorState

    check("ChatState has no coder_messages", "coder_messages" not in ChatState.model_fields)
    check("ChatState has no pending_reviews", "pending_reviews" not in ChatState.model_fields)
    check("chat uses its own message field", "chat_messages" in ChatState.model_fields)
    check("CoderState exposes result", "result" in CoderState.model_fields)
    check("SupervisorState has no coder_messages", "coder_messages" not in SupervisorState.model_fields)
    check("SupervisorState has no chat_messages", "chat_messages" not in SupervisorState.model_fields)
    check("SupervisorState reserves intent_reason", "intent_reason" in SupervisorState.model_fields)

    # ═══ 7. intent_reason 占位（第二轮审计拍板）═══
    # 规则：可选、不参与校验、不影响重试。缺/空/类型错 → None；超长截断。
    print("\n=== 7. intent_reason 占位 ===")
    install_intent(script=[json.dumps({"intent": "CHAT", "reason": "闲聊"})])
    chat_mod.chat_llm = FakeModel("好")
    state = await run_case(graph, "reason-ok", "在吗")
    check("reason captured", state.get("intent_reason") == "闲聊",
          str(state.get("intent_reason")))

    install_intent(script=[json.dumps({"intent": "CHAT"})])
    state = await run_case(graph, "reason-missing", "在吗")
    check("missing reason → None", state.get("intent_reason") is None,
          str(state.get("intent_reason")))

    install_intent(script=[json.dumps({"intent": "CHAT", "reason": 123})])
    state = await run_case(graph, "reason-badtype", "在吗")
    check("non-string reason → None, still routed",
          state.get("intent_reason") is None and state.get("intent") == "CHAT",
          str(state.get("intent_reason")))

    install_intent(script=[json.dumps({"intent": "CHAT", "reason": "很" * 300})])
    state = await run_case(graph, "reason-long", "在吗")
    check("long reason truncated, graph survives",
          state.get("intent") == "CHAT" and len(state.get("intent_reason") or "") == 255,
          f"n={len(state.get('intent_reason') or '')}")

    install_intent(script=[json.dumps({"intent": "RAG", "reason": "查资料"})])
    state = await run_case(graph, "reason-unsupported", "查资料")
    check("reason kept on route failure", state.get("intent_reason") == "查资料",
          str(state.get("intent_reason")))
    check("route_error carries reason", "模型理由：查资料" in (state.get("route_error") or ""),
          str(state.get("route_error")))

    # 重试耗尽时，最后一跳可能仍是"合法 JSON 但缺 intent 字段"——reason 要留住
    install_intent(script=[json.dumps({"intent": 123, "reason": "结构化输出"})])
    state = await run_case(graph, "reason-exhausted", "随便")
    check("route_status=failed", state.get("route_status") == "failed",
          str(state.get("route_status")))
    check("reason survives retry exhaustion", state.get("intent_reason") == "结构化输出",
          str(state.get("intent_reason")))
    check("exhausted route_error carries reason",
          "模型理由：结构化输出" in (state.get("route_error") or ""),
          str(state.get("route_error")))

    # 成功路由也要留一条可检索的痕迹（checkpoint 里的 intent_raw 没人会去翻）
    class _ListHandler(logging.Handler):
        def __init__(self) -> None:
            super().__init__()
            self.messages: list[str] = []

        def emit(self, record) -> None:
            self.messages.append(record.getMessage())

    handler = _ListHandler()
    sup_logger = logging.getLogger("furina_desktop.agent.nodes.supervisor")
    sup_logger.addHandler(handler)
    sup_logger.setLevel(logging.INFO)
    try:
        install_intent(script=[json.dumps({"intent": "CODE", "reason": "要改文件"})])
        coder_mod.llm_with_tools = FakeModel("改好了")
        await run_case(graph, "reason-log", "改一下配置")
    finally:
        sup_logger.removeHandler(handler)
    check("success route logged with intent+reason",
          any("intent=CODE" in m and "reason=要改文件" in m for m in handler.messages),
          str(handler.messages))

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

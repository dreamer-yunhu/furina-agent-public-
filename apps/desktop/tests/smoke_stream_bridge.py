"""SSE 桥 + 审批恢复冒烟测试（T1 / T2 / T3 / T15 验收）。

# ── AI-ASSISTED ── 本文件由 AI 生成，待人工复核 ──
# 复核重点：FakeStream 只替代 LLM 的"流式输出形状"；图、工具、interrupt、
# resume、沙箱落盘都是真的。用它证明 SSE 帧序，不证明真模型的 token 质量。

跑法（仓库根）：
    .venv-build\\Scripts\\python.exe apps\\desktop\\tests\\smoke_stream_bridge.py

覆盖：
    1. 首次 run：token 流 + tool_start + approval_required（含 diff、无绝对路径）
    2. 中断帧只下发一次（子图/根图各报一次，按 id 去重）
    3. 挂起期间再发新消息 → thread_suspended，不启动新 run
    4. 恢复：tool_end + 最终 token + done=completed + 文件真的落盘
    5. 非挂起线程 resume → not_suspended
    6. 决定与待审项不匹配 → decision_mismatch，且图仍挂起
    7. SupervisorState 的 mode 已删除、intent 无默认值（Stage A 反向断言）
"""
from __future__ import annotations

import asyncio
import json
import shutil
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "apps" / "desktop" / "src"))
sys.path.insert(0, str(ROOT / "packages" / "core" / "src"))

from langchain_core.language_models.chat_models import BaseChatModel  # noqa: E402
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage  # noqa: E402
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult  # noqa: E402
from langgraph.checkpoint.memory import InMemorySaver  # noqa: E402

from furina_core.config import settings  # noqa: E402
from furina_core.task.enums import ApprovalStatus  # noqa: E402
import furina_desktop.agent.nodes.coder as coder_mod  # noqa: E402
from furina_desktop.agent.build import build_graph  # noqa: E402
from furina_desktop.agent.contracts import ItemDecision, ReviewAction, ReviewDecision  # noqa: E402
from furina_desktop.agent.stream import (  # noqa: E402
    DecisionMismatch,
    agent_resume_stream,
    agent_stream,
    check_decision_matches,
    get_pending_tool_call_ids,
)
from furina_desktop.agent.tools.registry import read_file_tool, write_file_tool  # noqa: E402
from furina_desktop.api.contracts import AgentRequest  # noqa: E402
from _t23_testkit import config_for, install_intent, make_runtime, new_thread  # noqa: E402
from furina_desktop.agent.runtime import DecisionInput  # noqa: E402

PASS, FAIL = "PASS", "FAIL"
_results: list[tuple[str, bool]] = []


def check(label: str, ok: bool, extra: str = "") -> None:
    _results.append((label, ok))
    print(f"  [{PASS if ok else FAIL}] {label}" + (f"   {extra}" if extra else ""))


class FakeStream(BaseChatModel):
    """第 1 次：流式吐 3 个 token + 一个 write_file_tool 调用；第 2 次：流式吐 "done"。"""

    calls: int = 0

    @property
    def _llm_type(self) -> str:
        return "fake-stream"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        self.calls += 1
        if self.calls == 1:
            message = AIMessage(
                content="好的，",
                tool_calls=[{"name": "write_file_tool",
                             "args": {"file_path": "out.txt", "text": "approved!"},
                             "id": "call_w1"}],
            )
        else:
            message = AIMessage(content="done")
        return ChatResult(generations=[ChatGeneration(message=message)])

    async def _astream(self, messages, stop=None, run_manager=None, **kwargs):
        self.calls += 1
        if self.calls == 1:
            for piece in ("好", "的", "，"):
                yield ChatGenerationChunk(message=AIMessageChunk(content=piece))
            args = json.dumps({"file_path": "out.txt", "text": "approved!"})
            yield ChatGenerationChunk(
                message=AIMessageChunk(
                    content="",
                    tool_call_chunks=[{"name": "write_file_tool", "args": args,
                                       "id": "call_w1", "index": 0}],
                )
            )
        else:
            for piece in ("do", "ne"):
                yield ChatGenerationChunk(message=AIMessageChunk(content=piece))
        # 收尾空 chunk：下游必须丢弃，不能变成一个空 token 帧
        yield ChatGenerationChunk(message=AIMessageChunk(content=""))


def make_box() -> Path:
    box = ROOT / "_smoke_tmp" / "stream_bridge_sandbox"
    if box.exists():
        shutil.rmtree(box, ignore_errors=True)
    box.mkdir(parents=True, exist_ok=True)
    settings.sandbox_root = box
    read_file_tool.root_dir = str(box)
    write_file_tool.root_dir = str(box)
    return box


def parse_frames(raw_frames: list[str]) -> list[dict]:
    events = []
    for raw in raw_frames:
        assert raw.startswith("data: ") and raw.endswith("\n\n"), raw
        events.append(json.loads(raw[len("data: "):]))
    return events


def types_of(events: list[dict]) -> list[str]:
    return [e.get("type") for e in events]


def approve(tool_call_id: str) -> ReviewDecision:
    return ReviewDecision(decisions=[
        ItemDecision(tool_call_id=tool_call_id, action=ReviewAction.APPROVE, reason=None)
    ])


async def collect(gen) -> list[dict]:
    return parse_frames([frame async for frame in gen])


async def main() -> None:
    box = make_box()
    coder_mod.llm_with_tools = FakeStream()
    install_intent("CODE")  # <- AI 改动（Stage A）：测试不联网
    graph = build_graph(InMemorySaver())
    engine, factory, runtime, user_id = await make_runtime(
        ROOT / "_smoke_tmp" / "stream_bridge_db", sandbox=box
    )
    thread_id = await new_thread(factory, user_id, "stream")
    run = await runtime.start_run(thread_id=thread_id, instruction="write it")
    request = AgentRequest(user_input="write it", chat_thread_id=thread_id)

    # ═══ 1. 首次 run ═══
    print("=== 1. first run: tokens + approval_required ===")
    events = await collect(agent_stream(inform=request, graph=graph, run=run, runtime=runtime))
    t = types_of(events)
    check("has token frames", "token" in t, str(t))
    check("tokens assembled", "".join(e["content"] for e in events if e["type"] == "token") == "好的，")
    check("no empty token", all(e["content"] for e in events if e["type"] == "token"))
    check("has tool_start", "tool_start" in t)
    start = next((e for e in events if e["type"] == "tool_start"), {})
    check("tool_start id/name", start.get("id") == "call_w1" and start.get("name") == "write_file_tool", str(start))
    check("tool_start attributed to coder", start.get("agent") == "coder", str(start.get("agent")))

    approvals = [e for e in events if e["type"] == "approval_required"]
    check("approval_required exactly once (deduped)", len(approvals) == 1, f"n={len(approvals)}")
    approval = approvals[0] if approvals else {}
    check("approval has interrupt_id", bool(approval.get("interrupt_id")))
    check("approval attributed to coder", approval.get("agent") == "coder")
    reqs = (approval.get("review") or {}).get("requests") or []
    check("approval carries one request", len(reqs) == 1)
    req = reqs[0] if reqs else {}
    check("request bound to tool_call_id", req.get("tool_call_id") == "call_w1")
    check("request path is sandbox-relative", req.get("path") == "out.txt", str(req.get("path")))
    # T34：字段必须穿过 interrupt + SSE JSON 到达前端（根目录写入 → 空列表）
    check("creates_dirs survives the SSE payload", req.get("creates_dirs") == [],
          str(req.get("creates_dirs")))
    diff = req.get("diff") or ""
    check("diff contains new content", "approved!" in diff)
    check("diff has no absolute path", "C:\\" not in diff and str(box) not in diff, diff.splitlines()[:2])
    check("diff header uses a/out.txt", diff.startswith("--- a/out.txt"), diff.splitlines()[:1])
    check("done=interrupted", events[-1] == {"type": "done", "status": "interrupted"}, str(events[-1]))

    # ═══ 2. 挂起期间再来一条消息 ═══
    print("\n=== 2. new message while suspended ===")
    calls_before = coder_mod.llm_with_tools.calls
    events = await collect(agent_stream(inform=request, graph=graph, run=run, runtime=runtime))
    check("error=thread_suspended", events[0].get("code") == "thread_suspended", str(events[0]))
    check("pending ids echoed", events[0].get("pending_tool_call_ids") == ["call_w1"])
    check("done=interrupted", events[-1].get("status") == "interrupted")
    check("no new model call", coder_mod.llm_with_tools.calls == calls_before)
    check("file still absent", not (box / "out.txt").exists())

    # ═══ 3. 恢复 ═══
    print("\n=== 3. resume with approve ===")
    config = config_for(run)
    pending = await get_pending_tool_call_ids(graph=graph, config=config)
    check("pending ids readable", pending == ["call_w1"], str(pending))
    snap = await graph.aget_state(config)
    req_by_call = {
        req["tool_call_id"]: req["approval_id"]
        for interrupt in snap.interrupts
        for req in ((interrupt.value or {}).get("requests") or [])
    }
    await runtime.submit_decisions(
        thread_id=run.thread_id,
        execution_id=run.execution_id,
        decisions=[DecisionInput(
            decision=ApprovalStatus.APPROVED,
            approval_id=uuid.UUID(req_by_call["call_w1"]),
            tool_call_id="call_w1",
        )],
        decided_by="test",
    )
    events = await collect(agent_resume_stream(
        graph=graph, graph_thread_id=run.graph_thread_id,
        decision=approve("call_w1"), execution_id=run.execution_id, runtime=runtime,
    ))
    t = types_of(events)
    check("has tool_end", "tool_end" in t, str(t))
    end = next((e for e in events if e["type"] == "tool_end"), {})
    check("tool_end id/status", end.get("id") == "call_w1" and end.get("status") == "success", str(end))
    check("tool_end content", "成功" in (end.get("content") or ""), str(end.get("content")))
    check("resume tokens", "".join(e["content"] for e in events if e["type"] == "token") == "done")
    check("done=completed", events[-1] == {"type": "done", "status": "completed"}, str(events[-1]))
    check("file written", (box / "out.txt").is_file())
    check("file content correct", (box / "out.txt").read_text(encoding="utf-8") == "approved!")
    check("no pending after resume", (await get_pending_tool_call_ids(graph=graph, config=config)) == [])

    # ═══ 4. 非挂起线程 resume ═══
    print("\n=== 4. resume on a thread that is not suspended ===")
    fresh_thread = uuid.uuid4()
    events = await collect(agent_resume_stream(
        graph=graph, graph_thread_id=fresh_thread, decision=approve("call_w1")
    ))
    check("error=not_suspended", events[0].get("code") == "not_suspended", str(events[0]))
    check("done=completed", events[-1].get("status") == "completed")

    # ═══ 5. 决定与待审项不匹配 ═══
    print("\n=== 5. decision mismatch ===")
    # 换一个新假模型：上面 resume 已经把它推进到"不调工具"的第二次输出
    coder_mod.llm_with_tools = FakeStream()
    mismatch_thread = await new_thread(factory, user_id, "mismatch")
    mismatch_run = await runtime.start_run(thread_id=mismatch_thread, instruction="write it")
    await collect(agent_stream(
        inform=AgentRequest(user_input="write it", chat_thread_id=mismatch_thread),
        graph=graph, run=mismatch_run, runtime=runtime,
    ))
    mismatch_config = config_for(mismatch_run)
    events = await collect(agent_resume_stream(
        graph=graph, graph_thread_id=mismatch_run.graph_thread_id,
        decision=approve("call_forged"), execution_id=mismatch_run.execution_id, runtime=runtime,
    ))
    check("error=decision_mismatch", events[0].get("code") == "decision_mismatch", str(events[0]))
    check("done=interrupted", events[-1].get("status") == "interrupted")
    check("still pending", await get_pending_tool_call_ids(graph=graph, config=mismatch_config) == ["call_w1"])

    try:
        check_decision_matches(
            ReviewDecision(decisions=[
                ItemDecision(tool_call_id="call_w1", action=ReviewAction.APPROVE, reason=None),
                ItemDecision(tool_call_id="call_w1", action=ReviewAction.REJECT, reason="x"),
            ]),
            ["call_w1"],
        )
        check("duplicate decisions rejected", False)
    except DecisionMismatch:
        check("duplicate decisions rejected", True)

    # ═══ 6. mode 已迁移为 intent（Stage A · D-SUP-04） ═══
    # <- AI 改动（Stage A）：原断言是 "mode 有默认值 code"，那是 T3 的临时补丁。
    #    现在 mode 被删除，路由权威位是 intent。这里改成**反向断言**：
    #    谁要是把 mode 加回来，这条会先红。
    print("\n=== 6. mode removed / intent routed (Stage A) ===")
    from furina_desktop.agent.state import SupervisorState
    check("SupervisorState.mode removed", "mode" not in SupervisorState.model_fields)
    check("intent has no default", SupervisorState.model_fields["intent"].default is None,
          str(SupervisorState.model_fields["intent"].default))

    from furina_desktop.agent.runtime import set_runtime
    set_runtime(None)
    await engine.dispose()

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

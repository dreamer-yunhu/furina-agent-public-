# ── AI-ASSISTED ── 本文件由 AI 生成，待人工复核 ──
"""coder 子图审批链路（由 smoke_approval_flow.py 原生化）。

验的是**真实图 + 真实工具 + 真实 interrupt/resume**，只把 LLM 换成 FakeModel
（它需要网络与密钥）。所以这不是"模拟审批"。

覆盖：
    1. 安全工具直接执行，不进审批
    2. 高风险工具停在 interrupt，载荷含 path/diff；批准后文件真的出现
    3. 拒绝后文件不出现，且模型收到打回消息
    4. 未知工具被拦下
    5. 路径越界被拦下，且沙箱外什么都没创建

每个用例独立 runtime / DB / 沙箱，并在同一个事件循环内创建与释放。
"""

from __future__ import annotations

import asyncio
import uuid
from contextlib import asynccontextmanager

from langchain_core.messages import AIMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

import furina_desktop.agent.nodes.coder as coder_mod
from _t23_testkit import config_for, install_intent, make_runtime, new_thread, run_input
from furina_core.config import settings
from furina_core.task.enums import ApprovalStatus
from furina_desktop.agent.build import build_graph
from furina_desktop.agent.runtime import DecisionInput, set_runtime
from furina_desktop.agent.tools.registry import read_file_tool, write_file_tool


class FakeModel:
    """只替代 LLM：第一次产出指定 tool_calls，之后产出最终文本。"""

    def __init__(self, tool_calls: list[dict], final: str = "完成") -> None:
        self.tool_calls = tool_calls
        self.final = final
        self.calls = 0
        self.seen_tool_messages: list[ToolMessage] = []

    async def ainvoke(self, messages):
        self.calls += 1
        if self.calls == 1:
            return AIMessage(content="", tool_calls=self.tool_calls)
        self.seen_tool_messages = [m for m in messages if isinstance(m, ToolMessage)]
        return AIMessage(content=self.final)


class Env:
    def __init__(self, box, factory, runtime, user_id):
        self.box = box
        self.factory = factory
        self.runtime = runtime
        self.user_id = user_id


@asynccontextmanager
async def make_env(tmp_path):
    box = tmp_path / "sandbox"
    box.mkdir()
    settings.sandbox_root = box
    read_file_tool.root_dir = str(box)
    write_file_tool.root_dir = str(box)

    engine, factory, runtime, user_id = await make_runtime(tmp_path / "db", sandbox=box)
    try:
        yield Env(box, factory, runtime, user_id)
    finally:
        set_runtime(None)
        await engine.dispose()


async def persist_review(env: Env, graph, config, run, resume: dict) -> None:
    """T23-4：直接驱动图也必须先落库，否则认领会失败（fail-closed）。"""
    snapshot = await graph.aget_state(config)
    approval_by_call = {
        request["tool_call_id"]: request["approval_id"]
        for interrupt in snapshot.interrupts
        for request in ((interrupt.value or {}).get("requests") or [])
    }
    decisions = [
        DecisionInput(
            decision=(
                ApprovalStatus.APPROVED
                if decision["action"] == "approve"
                else ApprovalStatus.REJECTED
            ),
            approval_id=uuid.UUID(approval_by_call[decision["tool_call_id"]]),
            tool_call_id=decision["tool_call_id"],
            reason=decision.get("reason"),
        )
        for decision in resume["decisions"]
    ]
    await env.runtime.submit_decisions(
        thread_id=run.thread_id,
        execution_id=run.execution_id,
        decisions=decisions,
        decided_by="test",
    )


async def run_case(env: Env, name: str, tool_calls: list[dict], resume: dict | None = None):
    fake = FakeModel(tool_calls)
    coder_mod.llm_with_tools = fake
    install_intent("CODE")
    graph = build_graph(InMemorySaver())
    thread_id = await new_thread(env.factory, env.user_id, name)
    run = await env.runtime.start_run(thread_id=thread_id, instruction="执行任务")
    config = config_for(run)
    first = await graph.ainvoke(run_input("执行任务", run), config)
    if resume is not None:
        await persist_review(env, graph, config, run, resume)
        await graph.ainvoke(Command(resume=resume), config)
    return graph, config, fake, first, run


def tool_text(fake: FakeModel) -> str:
    return "".join(str(message.content) for message in fake.seen_tool_messages)


def test_safe_tool_skips_approval(tmp_path):
    async def scenario():
        async with make_env(tmp_path) as env:
            (env.box / "readme.txt").write_text("hello-furina", encoding="utf-8")
            _graph, _config, fake, _first, _run = await run_case(
                env,
                "t-safe",
                [
                    {
                        "name": "read_file_tool",
                        "args": {"file_path": "readme.txt"},
                        "id": "call_r1",
                    }
                ],
            )
            assert fake.calls >= 2, "安全工具不该停在中断"
            assert "hello-furina" in tool_text(fake)

    asyncio.run(scenario())


def test_high_risk_tool_requires_approval_and_writes(tmp_path):
    async def scenario():
        async with make_env(tmp_path) as env:
            graph, config, _fake, _first, run = await run_case(
                env,
                "t-approve",
                [
                    {
                        "name": "write_file_tool",
                        "args": {"file_path": "out.txt", "text": "approved!"},
                        "id": "call_w1",
                    }
                ],
            )

            state = await graph.aget_state(config)
            assert len(state.interrupts) == 1, "图没有停在 interrupt"
            payload = state.interrupts[0].value or {}
            assert payload.get("requests"), payload
            request = payload["requests"][0]
            assert request.get("path") == "out.txt"
            assert "approved!" in (request.get("diff") or "")

            resume = {
                "type": "review_decision",
                "decisions": [
                    {"tool_call_id": "call_w1", "action": "approve", "reason": None}
                ],
            }
            await persist_review(env, graph, config, run, resume)
            await graph.ainvoke(Command(resume=resume), config)

            assert (env.box / "out.txt").is_file()
            assert (env.box / "out.txt").read_text(encoding="utf-8") == "approved!"

    asyncio.run(scenario())


def test_rejected_tool_does_not_write(tmp_path):
    async def scenario():
        async with make_env(tmp_path) as env:
            _graph, _config, fake, _first, _run = await run_case(
                env,
                "t-reject",
                [
                    {
                        "name": "write_file_tool",
                        "args": {"file_path": "denied.txt", "text": "nope"},
                        "id": "call_w2",
                    }
                ],
                resume={
                    "type": "review_decision",
                    "decisions": [
                        {"tool_call_id": "call_w2", "action": "reject", "reason": "不允许"}
                    ],
                },
            )
            assert not (env.box / "denied.txt").exists()
            assert "拒绝" in tool_text(fake)

    asyncio.run(scenario())


def test_unknown_tool_is_blocked(tmp_path):
    async def scenario():
        async with make_env(tmp_path) as env:
            graph, config, fake, _first, _run = await run_case(
                env, "t-unknown", [{"name": "hack_tool", "args": {}, "id": "call_x1"}]
            )
            state = await graph.aget_state(config)
            assert len(state.interrupts) == 0, "未知工具不该进入审批"
            assert "未知工具" in tool_text(fake)

    asyncio.run(scenario())


def test_path_traversal_is_blocked(tmp_path):
    async def scenario():
        async with make_env(tmp_path) as env:
            outside = env.box.parent / "escape.txt"
            graph, config, fake, _first, _run = await run_case(
                env,
                "t-escape",
                [
                    {
                        "name": "write_file_tool",
                        "args": {"file_path": "../escape.txt", "text": "x"},
                        "id": "call_e1",
                    }
                ],
            )
            state = await graph.aget_state(config)
            assert len(state.interrupts) == 0, "越界不该进入审批"
            assert not outside.exists(), "沙箱外被创建了文件"
            assert "审批载荷构造失败" in tool_text(fake)

    asyncio.run(scenario())

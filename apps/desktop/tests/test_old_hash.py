# ── AI-ASSISTED ── 本文件由 AI 生成，待人工复核 ──
"""审批期间文件变化 → 批准也不能覆盖（由 smoke_old_hash.py 原生化）。

复核重点：
    验证的是 **execute_node 在放行前重新读文件并比哈希** 这条判断。
    它**不能**证明 TOCTOU 被完全消除（校验到 ToolNode 落盘仍有间隙，见 T23）。

覆盖四种情况：
    1. 既有文件在挂起期间被改 → 不覆盖，模型被告知"已被修改"
    2. 新建目标在挂起期间被别人创建 → 不覆盖，模型被告知"已被创建"
    3. 既有文件在挂起期间被删 → 不重建，模型被告知"已被删除"
    4. 什么都没变 → 正常写入

每个用例用**独立的 runtime / DB / 沙箱**，并在同一个事件循环里创建与释放
（aiosqlite 的连接绑定 loop，跨 asyncio.run 复用会出问题）。
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
    """第一次产出写文件调用；第二次记录它收到的 ToolMessage 并返回文本。"""

    def __init__(self, tool_calls: list[dict]) -> None:
        self.tool_calls = tool_calls
        self.calls = 0
        self.seen_tool_messages: list[ToolMessage] = []

    async def ainvoke(self, messages):
        self.calls += 1
        if self.calls == 1:
            return AIMessage(content="", tool_calls=self.tool_calls)
        self.seen_tool_messages = [m for m in messages if isinstance(m, ToolMessage)]
        return AIMessage(content="完成")


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

    engine, factory, runtime, user_id = await make_runtime(
        tmp_path / "db", sandbox=box
    )
    try:
        yield Env(box, factory, runtime, user_id)
    finally:
        set_runtime(None)
        await engine.dispose()


async def start_pending(env: Env, thread: str, file_path: str, text: str):
    fake = FakeModel(
        [
            {
                "name": "write_file_tool",
                "args": {"file_path": file_path, "text": text},
                "id": "call_t14",
            }
        ]
    )
    coder_mod.llm_with_tools = fake
    install_intent("CODE")
    graph = build_graph(InMemorySaver())
    thread_id = await new_thread(env.factory, env.user_id, thread)
    run = await env.runtime.start_run(thread_id=thread_id, instruction="写入")
    config = config_for(run)
    await graph.ainvoke(run_input("写入", run), config)
    snapshot = await graph.aget_state(config)
    assert snapshot.interrupts, "图没有停在中断上"
    return graph, config, fake, run


async def approve_pending(env: Env, graph, config, run, tool_call_id: str) -> Command:
    """T23-4：先落库 APPROVED，再恢复图。"""
    snapshot = await graph.aget_state(config)
    approval_by_call = {
        request["tool_call_id"]: request["approval_id"]
        for interrupt in snapshot.interrupts
        for request in ((interrupt.value or {}).get("requests") or [])
    }
    await env.runtime.submit_decisions(
        thread_id=run.thread_id,
        execution_id=run.execution_id,
        decisions=[
            DecisionInput(
                decision=ApprovalStatus.APPROVED,
                approval_id=uuid.UUID(approval_by_call[tool_call_id]),
                tool_call_id=tool_call_id,
            )
        ],
        decided_by="test",
    )
    return Command(
        resume={
            "type": "review_decision",
            "decisions": [
                {"tool_call_id": tool_call_id, "action": "approve", "reason": None}
            ],
        }
    )


def model_text(fake: FakeModel) -> str:
    return "".join(str(message.content) for message in fake.seen_tool_messages)


def test_existing_file_modified_while_pending(tmp_path):
    async def scenario():
        async with make_env(tmp_path) as env:
            (env.box / "doc.txt").write_text("original", encoding="utf-8")
            graph, config, fake, run = await start_pending(
                env, "t14-modified", "doc.txt", "from-model"
            )
            (env.box / "doc.txt").write_text("edited-by-human", encoding="utf-8")
            await graph.ainvoke(
                await approve_pending(env, graph, config, run, "call_t14"), config
            )
            assert (env.box / "doc.txt").read_text(encoding="utf-8") == "edited-by-human"
            text = model_text(fake)
            assert "审批已失效" in text, text[:120]
            assert "已被修改" in text, text[:120]

    asyncio.run(scenario())


def test_new_target_created_while_pending(tmp_path):
    async def scenario():
        async with make_env(tmp_path) as env:
            graph, config, fake, run = await start_pending(
                env, "t14-created", "new.txt", "from-model"
            )
            (env.box / "new.txt").write_text("someone-else", encoding="utf-8")
            await graph.ainvoke(
                await approve_pending(env, graph, config, run, "call_t14"), config
            )
            assert (env.box / "new.txt").read_text(encoding="utf-8") == "someone-else"
            assert "已被创建" in model_text(fake)

    asyncio.run(scenario())


def test_existing_file_deleted_while_pending(tmp_path):
    async def scenario():
        async with make_env(tmp_path) as env:
            (env.box / "gone.txt").write_text("to-be-deleted", encoding="utf-8")
            graph, config, fake, run = await start_pending(
                env, "t14-deleted", "gone.txt", "from-model"
            )
            (env.box / "gone.txt").unlink()
            await graph.ainvoke(
                await approve_pending(env, graph, config, run, "call_t14"), config
            )
            assert not (env.box / "gone.txt").exists()
            assert "已被删除" in model_text(fake)

    asyncio.run(scenario())


def test_unchanged_file_is_written(tmp_path):
    async def scenario():
        async with make_env(tmp_path) as env:
            (env.box / "ok.txt").write_text("before", encoding="utf-8")
            graph, config, _fake, run = await start_pending(
                env, "t14-clean", "ok.txt", "after"
            )
            await graph.ainvoke(
                await approve_pending(env, graph, config, run, "call_t14"), config
            )
            assert (env.box / "ok.txt").read_text(encoding="utf-8") == "after"

    asyncio.run(scenario())

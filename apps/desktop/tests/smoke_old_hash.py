"""T14 冒烟：审批期间目标文件变了，批准也不能覆盖。

# ── AI-ASSISTED ── 本文件由 AI 生成，待人工复核 ──
# 复核重点：验证的是"execute_node 在放行前重新读文件比哈希"这条判断。
# 它不能证明 TOCTOU 被完全消除（校验到 ToolNode 落盘仍有间隙，见 T23）。

跑法（仓库根）：
    .venv-build\\Scripts\\python.exe apps\\desktop\\tests\\smoke_old_hash.py

覆盖：
    1. 既有文件在挂起期间被改 → 批准后不覆盖，模型收到"已被修改"
    2. 新建目标在挂起期间被别人创建 → 批准后不覆盖，模型收到"已被创建"
    3. 既有文件在挂起期间被删 → 批准后不重建，模型收到"已被删除"
    4. 什么都没变 → 正常写入
"""
from __future__ import annotations

import asyncio
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "apps" / "desktop" / "src"))
sys.path.insert(0, str(ROOT / "packages" / "core" / "src"))

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage  # noqa: E402
from langgraph.checkpoint.memory import InMemorySaver  # noqa: E402
from langgraph.types import Command  # noqa: E402

from furina_core.config import settings  # noqa: E402
from furina_core.task.enums import ApprovalStatus  # noqa: E402
import furina_desktop.agent.nodes.coder as coder_mod  # noqa: E402
from furina_desktop.agent.build import build_graph  # noqa: E402
from furina_desktop.agent.tools.registry import read_file_tool, write_file_tool  # noqa: E402
from _t23_testkit import config_for, make_runtime, new_thread, run_input  # noqa: E402
from furina_desktop.agent.runtime import DecisionInput  # noqa: E402
import uuid  # noqa: E402

PASS, FAIL = "PASS", "FAIL"
_results: list[tuple[str, bool]] = []


def check(label: str, ok: bool, extra: str = "") -> None:
    _results.append((label, ok))
    print(f"  [{PASS if ok else FAIL}] {label}" + (f"   {extra}" if extra else ""))


class FakeModel:
    """第一次产出写文件调用；第二次只记录它收到的 ToolMessage 并返回文本。"""

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


def sandbox() -> Path:
    path = ROOT / "_smoke_tmp" / "old_hash_sandbox"
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)
    path.mkdir(parents=True, exist_ok=True)
    settings.sandbox_root = path
    read_file_tool.root_dir = str(path)
    write_file_tool.root_dir = str(path)
    return path


def approve(tool_call_id: str) -> Command:
    return Command(resume={
        "type": "review_decision",
        "decisions": [{"tool_call_id": tool_call_id, "action": "approve", "reason": None}],
    })


_runtime = None
_factory = None
_user_id = None


async def start_pending(thread: str, file_path: str, text: str):
    fake = FakeModel([{"name": "write_file_tool",
                       "args": {"file_path": file_path, "text": text},
                       "id": "call_t14"}])
    coder_mod.llm_with_tools = fake
    graph = build_graph(InMemorySaver())
    thread_id = await new_thread(_factory, _user_id, thread)
    run = await _runtime.start_run(thread_id=thread_id, instruction="写入")
    config = config_for(run)
    await graph.ainvoke(run_input("写入", run), config)
    snap = await graph.aget_state(config)
    assert snap.interrupts, "expected the graph to stop at an interrupt"
    return graph, config, fake, run


async def approve_pending(graph, config, run, tool_call_id: str) -> Command:
    """T23-4：先落库 APPROVED，再恢复图。"""
    snap = await graph.aget_state(config)
    req_by_call = {
        req["tool_call_id"]: req["approval_id"]
        for interrupt in snap.interrupts
        for req in ((interrupt.value or {}).get("requests") or [])
    }
    await _runtime.submit_decisions(
        thread_id=run.thread_id,
        execution_id=run.execution_id,
        decisions=[DecisionInput(
            decision=ApprovalStatus.APPROVED,
            approval_id=uuid.UUID(req_by_call[tool_call_id]),
            tool_call_id=tool_call_id,
        )],
        decided_by="test",
    )
    return approve(tool_call_id)


def model_text(fake: FakeModel) -> str:
    return "".join(str(m.content) for m in fake.seen_tool_messages)


async def main() -> None:
    global _runtime, _factory, _user_id
    box = sandbox()
    _engine, _factory, _runtime, _user_id = await make_runtime(
        ROOT / "_smoke_tmp" / "old_hash_db", sandbox=box
    )

    print("=== 1. existing file modified while pending ===")
    (box / "doc.txt").write_text("original", encoding="utf-8")
    graph, config, fake, run = await start_pending("t14-modified", "doc.txt", "from-model")
    (box / "doc.txt").write_text("edited-by-human", encoding="utf-8")
    await graph.ainvoke(await approve_pending(graph, config, run, "call_t14"), config)
    check("file NOT overwritten",
          (box / "doc.txt").read_text(encoding="utf-8") == "edited-by-human")
    got = model_text(fake)
    check("model told the approval is void", "审批已失效" in got, got[:80])
    check("model told which file changed", "已被修改" in got, got[:80])

    print("\n=== 2. new target created while pending ===")
    graph, config, fake, run = await start_pending("t14-created", "new.txt", "from-model")
    (box / "new.txt").write_text("someone-else", encoding="utf-8")
    await graph.ainvoke(await approve_pending(graph, config, run, "call_t14"), config)
    check("pre-existing content kept",
          (box / "new.txt").read_text(encoding="utf-8") == "someone-else")
    got = model_text(fake)
    check("model told file was created", "已被创建" in got, got[:80])

    print("\n=== 3. existing file deleted while pending ===")
    (box / "gone.txt").write_text("to-be-deleted", encoding="utf-8")
    graph, config, fake, run = await start_pending("t14-deleted", "gone.txt", "from-model")
    (box / "gone.txt").unlink()
    await graph.ainvoke(await approve_pending(graph, config, run, "call_t14"), config)
    check("deleted file NOT recreated", not (box / "gone.txt").exists())
    got = model_text(fake)
    check("model told file was deleted", "已被删除" in got, got[:80])

    print("\n=== 4. nothing changed ===")
    (box / "ok.txt").write_text("before", encoding="utf-8")
    graph, config, fake, run = await start_pending("t14-clean", "ok.txt", "after")
    await graph.ainvoke(await approve_pending(graph, config, run, "call_t14"), config)
    check("file written normally",
          (box / "ok.txt").read_text(encoding="utf-8") == "after")

    from furina_desktop.agent.runtime import set_runtime
    set_runtime(None)
    await _engine.dispose()

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

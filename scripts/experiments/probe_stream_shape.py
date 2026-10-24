"""探测 v2：把 messages / values / resume 三种帧的**节点归属**和**重复**情况钉死。

# ── AI-ASSISTED ── 本文件由 AI 生成，待人工复核 ──
# 复核重点：结论只对 langgraph 1.2.11 + 当前 FakeModel（非流式 ainvoke）成立。

跑法（仓库根）：
    .venv-build\\Scripts\\python.exe scripts\\experiments\\probe_stream_shape.py
"""
from __future__ import annotations

import asyncio
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps" / "desktop" / "src"))
sys.path.insert(0, str(ROOT / "packages" / "core" / "src"))

from langchain_core.messages import AIMessage, HumanMessage  # noqa: E402
from langgraph.checkpoint.memory import InMemorySaver  # noqa: E402
from langgraph.types import Command  # noqa: E402

from furina_core.config import settings  # noqa: E402
import furina_desktop.agent.nodes.coder as coder_mod  # noqa: E402
from furina_desktop.agent.build import build_graph  # noqa: E402
from furina_desktop.agent.tools.registry import read_file_tool, write_file_tool  # noqa: E402

APPROVE = {
    "type": "review_decision",
    "decisions": [{"tool_call_id": "call_w1", "action": "approve", "reason": None}],
}


class FakeModel:
    """第一次吐 tool_calls，之后吐最终文本。"""

    def __init__(self) -> None:
        self.calls = 0

    async def ainvoke(self, messages):
        self.calls += 1
        if self.calls == 1:
            return AIMessage(
                content="",
                tool_calls=[{"name": "write_file_tool",
                             "args": {"file_path": "out.txt", "text": "approved!"},
                             "id": "call_w1"}],
            )
        return AIMessage(content="done")


def make_box(tag: str) -> Path:
    box = ROOT / "_smoke_tmp" / f"probe2_{tag}"
    if box.exists():
        shutil.rmtree(box, ignore_errors=True)
    box.mkdir(parents=True, exist_ok=True)
    settings.sandbox_root = box
    read_file_tool.root_dir = str(box)
    write_file_tool.root_dir = str(box)
    return box


def fresh(tag: str):
    box = make_box(tag)
    coder_mod.llm_with_tools = FakeModel()
    graph = build_graph(InMemorySaver())
    config = {"configurable": {"thread_id": f"probe2-{tag}"}}
    inputs = {
        "messages": [HumanMessage(content="write it")],
        "mode": "code",
        "subagent_task": "write it",
    }
    return box, graph, config, inputs


def show(kind: str, payload) -> None:
    if kind == "messages":
        msg, meta = payload
        print(f"  [messages] node={meta.get('langgraph_node')!r} "
              f"ns={meta.get('langgraph_checkpoint_ns')!r} "
              f"type={type(msg).__name__} id={getattr(msg, 'id', None)!r} "
              f"content={msg.content!r} tool_calls={getattr(msg, 'tool_calls', None)!r}")
    elif kind == "values":
        has_int = "__interrupt__" in payload
        print(f"  [values]   keys={sorted(payload)} has___interrupt__={has_int}")
        if has_int:
            for it in payload["__interrupt__"]:
                print(f"             interrupt.id={it.id!r} value_keys={sorted(it.value) if isinstance(it.value, dict) else '?'}")
    elif kind == "updates":
        print(f"  [updates]  keys={sorted(payload)}")
    else:
        print(f"  [{kind}] {payload!r}")


async def run(tag: str, modes: list[str], do_resume: bool) -> None:
    print(f"\n===== {tag}  modes={modes} resume={do_resume} =====")
    box, graph, config, inputs = fresh(tag)

    print("-- 第一次 run --")
    async for chunk in graph.astream(inputs, config=config, stream_mode=modes):
        mode, payload = chunk if isinstance(chunk, tuple) else ("?", chunk)
        show(mode, payload)

    snap = await graph.aget_state(config)
    print(f"-- 快照 next={snap.next} n_interrupts={len(snap.interrupts)}")

    if do_resume:
        print("-- resume --")
        async for chunk in graph.astream(Command(resume=APPROVE), config=config, stream_mode=modes):
            mode, payload = chunk if isinstance(chunk, tuple) else ("?", chunk)
            show(mode, payload)
        snap = await graph.aget_state(config)
        print(f"-- 快照 next={snap.next} n_interrupts={len(snap.interrupts)} "
              f"file_exists={(box / 'out.txt').is_file()}")


async def main() -> None:
    # 关键对比：messages-only / 双模式 / 三模式
    await run("MsgsOnly", ["messages"], do_resume=True)
    await run("MsgVal", ["messages", "values"], do_resume=True)
    await run("All3", ["messages", "values", "updates"], do_resume=True)
    await run("ValOnly", ["values"], do_resume=True)


if __name__ == "__main__":
    asyncio.run(main())

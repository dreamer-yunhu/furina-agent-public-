"""探测 v3：用**会流式的假模型**回答 T1 最关键的三个问题。

# ── AI-ASSISTED ── 本文件由 AI 生成，待人工复核 ──
# 复核重点：FakeStream 只是替身；真模型（DeepSeek）的 chunk 形状若不同，
# 以真模型实测为准。本文件只钉"图这一层的帧序"，不钉"模型这一层的 chunk"。

要回答：
    Q1 第一次 run 在 interrupt 前，messages 模式有没有吐出 token？
    Q2 subgraphs=True 时 chunk 形状变成什么？能不能看到 coder_messages？
    Q3 中断帧在 subgraphs=True 下长什么样？能不能判断是哪个子图中断？
    Q4 resume 时 messages 会不会把中断前的消息**重放**一遍？
"""
from __future__ import annotations

import asyncio
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps" / "desktop" / "src"))
sys.path.insert(0, str(ROOT / "packages" / "core" / "src"))

from langchain_core.language_models.chat_models import BaseChatModel  # noqa: E402
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage  # noqa: E402
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult  # noqa: E402
from langgraph.checkpoint.memory import InMemorySaver  # noqa: E402
from langgraph.types import Command  # noqa: E402

from furina_core.config import settings  # noqa: E402
import furina_desktop.agent.nodes.coder as coder_mod  # noqa: E402
from furina_desktop.agent.build import build_graph  # noqa: E402
from furina_desktop.agent.tools.registry import read_file_tool, write_file_tool  # noqa: E402

APPROVE = {"type": "review_decision",
           "decisions": [{"tool_call_id": "call_w1", "action": "approve", "reason": None}]}


class FakeStream(BaseChatModel):
    """第 1 次：流式吐 3 个 token + 一个 tool_call；第 2 次：流式吐 "done"。"""

    calls: int = 0

    @property
    def _llm_type(self) -> str:
        return "fake-stream"

    def bind_tools(self, tools, **kwargs):  # noqa: D401
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        raise NotImplementedError("probe only uses astream")

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


def make_box(tag: str) -> Path:
    box = ROOT / "_smoke_tmp" / f"probe3_{tag}"
    if box.exists():
        shutil.rmtree(box, ignore_errors=True)
    box.mkdir(parents=True, exist_ok=True)
    settings.sandbox_root = box
    read_file_tool.root_dir = str(box)
    write_file_tool.root_dir = str(box)
    return box


def fresh(tag: str):
    box = make_box(tag)
    coder_mod.llm_with_tools = FakeStream()
    graph = build_graph(InMemorySaver())
    config = {"configurable": {"thread_id": f"probe3-{tag}"}}
    inputs = {"messages": [HumanMessage(content="write it")],
              "mode": "code", "subagent_task": "write it"}
    return box, graph, config, inputs


def show(kind: str, payload, ns=None) -> None:
    prefix = f"ns={list(ns) if ns else []} " if ns is not None else ""
    if kind == "messages":
        msg, meta = payload
        print(f"  {prefix}[messages] node={meta.get('langgraph_node')!r} "
              f"type={type(msg).__name__} content={msg.content!r} "
              f"tool_call_chunks={getattr(msg, 'tool_call_chunks', None)!r}")
    elif kind == "values":
        print(f"  {prefix}[values] keys={sorted(payload)}")
    elif kind == "updates":
        print(f"  {prefix}[updates] keys={sorted(payload)}")
    else:
        print(f"  {prefix}[{kind}] {payload!r}")


async def scenario(tag: str, modes: list[str], subgraphs: bool) -> None:
    print(f"\n===== {tag} modes={modes} subgraphs={subgraphs} =====")
    box, graph, config, inputs = fresh(tag)
    print("-- run #1 --")
    async for chunk in graph.astream(inputs, config=config, stream_mode=modes, subgraphs=subgraphs):
        if subgraphs:
            ns, mode, payload = chunk
            show(mode, payload, ns)
        else:
            show(chunk[0] if isinstance(chunk, tuple) else "?", chunk[1] if isinstance(chunk, tuple) else chunk)
    snap = await graph.aget_state(config)
    print(f"-- next={snap.next} n_interrupts={len(snap.interrupts)}")

    print("-- resume --")
    async for chunk in graph.astream(Command(resume=APPROVE), config=config,
                                     stream_mode=modes, subgraphs=subgraphs):
        if subgraphs:
            ns, mode, payload = chunk
            show(mode, payload, ns)
        else:
            show(chunk[0] if isinstance(chunk, tuple) else "?", chunk[1] if isinstance(chunk, tuple) else chunk)
    print(f"-- file_exists={(box / 'out.txt').is_file()}")


async def main() -> None:
    await scenario("plain", ["messages", "values"], False)
    await scenario("sub", ["messages", "values", "updates"], True)
    await scenario("plainupd", ["messages", "values", "updates"], False)


if __name__ == "__main__":
    asyncio.run(main())

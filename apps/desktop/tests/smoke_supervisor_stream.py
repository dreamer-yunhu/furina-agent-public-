"""Stage A · Phase 3/4 冒烟：主管图的 SSE 归属与失败收尾。

# ── AI-ASSISTED ── 本文件由 AI 生成，待人工复核 ──
# 类型：真图 + 真 SQLite 业务库 + 会流式的假模型（BaseChatModel 子类）。
# 关键点：假模型**实现了 `_astream`**，所以连 `ainvoke` 都会被 LangGraph 改写成流式 ——
#        这正是意图 token 可能泄漏的真实条件（报告 §R4 的探针 B）。

跑法（仓库根）：
    .venv-build\\Scripts\\python.exe apps\\desktop\\tests\\smoke_supervisor_stream.py

覆盖：
    1. CHAT：token 全归 chat，主管零 token；Task 落 COMPLETED
    2. CODE：主管→coder 正常收尾；Task 落 COMPLETED
    3. 路由失败：error=route_failed + done=failed；Task 落 FAILED（D-SUP-06 核心）
    4. CHAT 模型异常：error=graph_error + done=failed + Task FAILED
    5. CODE 图异常：done=failed + Task FAILED
"""

from __future__ import annotations

import asyncio
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "apps" / "desktop" / "src"))
sys.path.insert(0, str(ROOT / "packages" / "core" / "src"))

from sqlalchemy import select  # noqa: E402
from langchain_core.language_models.chat_models import BaseChatModel  # noqa: E402
from langchain_core.messages import AIMessage, AIMessageChunk  # noqa: E402
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult  # noqa: E402
from langgraph.checkpoint.memory import InMemorySaver  # noqa: E402

from furina_core.config import settings  # noqa: E402
from furina_core.task.enums import TaskStatus  # noqa: E402
from furina_core.task.models import AgentTask  # noqa: E402
import furina_desktop.agent.nodes.chat as chat_mod  # noqa: E402
import furina_desktop.agent.nodes.coder as coder_mod  # noqa: E402
import furina_desktop.agent.nodes.supervisor as supervisor_mod  # noqa: E402
from furina_desktop.agent.build import build_graph  # noqa: E402
from furina_desktop.agent.stream import agent_stream  # noqa: E402
from furina_desktop.api.contracts import AgentRequest  # noqa: E402
from furina_desktop.agent.tools.registry import read_file_tool, write_file_tool  # noqa: E402
from _t23_testkit import make_runtime, new_thread  # noqa: E402

PASS, FAIL = "PASS", "FAIL"
_results: list[tuple[str, bool]] = []


def check(label: str, ok: bool, extra: str = "") -> None:
    _results.append((label, ok))
    print(f"  [{PASS if ok else FAIL}] {label}" + (f"   {extra}" if extra else ""))


class StreamingFake(BaseChatModel):
    """会分块吐字的假模型（模仿 ChatOpenAI：实现 `_stream`/`_astream`）。

    `text` 是完整回答；流式时按 3 个字符一组切块，最后补一个空 chunk
    （真实模型也会发空收尾帧，SSE 层必须丢弃）。
    """

    text: str = ""

    @property
    def _llm_type(self) -> str:
        return "stage-a-streaming-fake"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=self.text))])

    def _stream(self, messages, stop=None, run_manager=None, **kwargs):
        for piece in _chunks(self.text):
            yield ChatGenerationChunk(message=AIMessageChunk(content=piece))
        yield ChatGenerationChunk(message=AIMessageChunk(content=""))

    async def _astream(self, messages, stop=None, run_manager=None, **kwargs):
        for piece in _chunks(self.text):
            yield ChatGenerationChunk(message=AIMessageChunk(content=piece))
        yield ChatGenerationChunk(message=AIMessageChunk(content=""))


def _chunks(text: str) -> list[str]:
    return [text[i : i + 3] for i in range(0, len(text), 3)]


class RaisingModel:
    """模型调用直接抛异常（模拟供应商故障）。"""

    async def ainvoke(self, messages):
        raise RuntimeError("model unavailable")


class ScriptedIntent:
    """意图替身：按脚本返回（可模拟非法输出），并记录调用次数。"""

    def __init__(self, script: list[str]) -> None:
        self.script = script
        self.calls = 0

    async def ainvoke(self, messages):
        self.calls += 1
        text = self.script.pop(0) if len(self.script) > 1 else self.script[0]
        return AIMessage(content=text)


def parse_frames(raw_frames: list[str]) -> list[dict]:
    events = []
    for raw in raw_frames:
        assert raw.startswith("data: ") and raw.endswith("\n\n"), raw
        events.append(json.loads(raw[len("data: ") :]))
    return events


async def collect(gen) -> list[dict]:
    return parse_frames([frame async for frame in gen])


async def task_status(factory, task_id) -> str | None:
    async with factory() as session:
        row = (
            await session.execute(select(AgentTask).where(AgentTask.id == task_id))
        ).scalars().first()
        return row.status if row else None


async def main() -> None:
    box = ROOT / "_smoke_tmp" / "supervisor_stream_sandbox"
    if box.exists():
        shutil.rmtree(box, ignore_errors=True)
    box.mkdir(parents=True, exist_ok=True)
    settings.sandbox_root = box
    read_file_tool.root_dir = str(box)
    write_file_tool.root_dir = str(box)

    graph = build_graph(InMemorySaver())
    engine, factory, runtime, user_id = await make_runtime(
        ROOT / "_smoke_tmp" / "supervisor_stream_db", sandbox=box
    )

    # ═══ 1. CHAT ═══
    print("=== 1. CHAT：token 归 chat，主管零 token ===")
    # 关键：意图模型也会流式吐字（它会吐出 {"intent": "CHAT"} 的碎片）
    supervisor_mod.intent_llm = StreamingFake(text=json.dumps({"intent": "CHAT"}))
    chat_mod.chat_llm = StreamingFake(text="我在呢，今天想聊点什么？")
    thread_id = await new_thread(factory, user_id, "chat")
    run = await runtime.start_run(thread_id=thread_id, instruction="在吗")
    events = await collect(agent_stream(
        inform=AgentRequest(user_input="在吗", chat_thread_id=thread_id),
        graph=graph, run=run, runtime=runtime,
    ))
    tokens = [e for e in events if e["type"] == "token"]
    check("has tokens", bool(tokens), str([e["type"] for e in events]))
    check("all tokens attributed to chat",
          all(e.get("agent") == "chat" for e in tokens),
          str(sorted({e.get("agent") for e in tokens})))
    check("no supervisor tokens leaked", not any(e.get("agent") == "supervisor" for e in tokens))
    check("no intent text in tokens",
          not any("intent" in (e.get("content") or "") for e in tokens),
          "".join(e.get("content") or "" for e in tokens)[:60])
    check("tokens reassemble the reply",
          "".join(e["content"] for e in tokens) == "我在呢，今天想聊点什么？",
          "".join(e["content"] for e in tokens))
    check("done=completed", events[-1] == {"type": "done", "status": "completed"}, str(events[-1]))
    check("task COMPLETED", await task_status(factory, run.task_id) == TaskStatus.COMPLETED.value,
          str(await task_status(factory, run.task_id)))

    # ═══ 2. CODE ═══
    print("\n=== 2. CODE：主管 → coder 正常收尾 ===")
    supervisor_mod.intent_llm = StreamingFake(text=json.dumps({"intent": "CODE"}))
    coder_mod.llm_with_tools = StreamingFake(text="改好了")
    thread2 = await new_thread(factory, user_id, "code")
    run2 = await runtime.start_run(thread_id=thread2, instruction="改一下 readme")
    events = await collect(agent_stream(
        inform=AgentRequest(user_input="改一下 readme", chat_thread_id=thread2),
        graph=graph, run=run2, runtime=runtime,
    ))
    tokens = [e for e in events if e["type"] == "token"]
    check("tokens attributed to coder", tokens and all(e.get("agent") == "coder" for e in tokens),
          str(sorted({e.get("agent") for e in tokens})))
    check("no supervisor tokens", not any(e.get("agent") == "supervisor" for e in tokens))
    check("done=completed", events[-1] == {"type": "done", "status": "completed"}, str(events[-1]))
    check("task COMPLETED", await task_status(factory, run2.task_id) == TaskStatus.COMPLETED.value,
          str(await task_status(factory, run2.task_id)))

    # ═══ 3. 路由失败 ═══
    print("\n=== 3. 路由失败：不得记成 COMPLETED ===")
    supervisor_mod.intent_llm = ScriptedIntent(["我不会 JSON", "我依然不会"])
    thread3 = await new_thread(factory, user_id, "fail")
    run3 = await runtime.start_run(thread_id=thread3, instruction="随便")
    events = await collect(agent_stream(
        inform=AgentRequest(user_input="随便", chat_thread_id=thread3),
        graph=graph, run=run3, runtime=runtime,
    ))
    types = [e["type"] for e in events]
    check("error frame emitted", "error" in types, str(types))
    err = next((e for e in events if e["type"] == "error"), {})
    check("error code=route_failed", err.get("code") == "route_failed", str(err.get("code")))
    check("message explains retry exhaustion", "重试" in (err.get("message") or ""),
          str(err.get("message")))
    check("done=failed", events[-1] == {"type": "done", "status": "failed"}, str(events[-1]))
    check("task FAILED (not COMPLETED)",
          await task_status(factory, run3.task_id) == TaskStatus.FAILED.value,
          str(await task_status(factory, run3.task_id)))
    check("no token frames", not any(t == "token" for t in types))

    # ═══ 4. CHAT 模型异常 ═══
    print("\n=== 4. CHAT 模型异常 → failed，不伪装成完成 ===")
    supervisor_mod.intent_llm = StreamingFake(text=json.dumps({"intent": "CHAT"}))
    chat_mod.chat_llm = RaisingModel()
    thread4 = await new_thread(factory, user_id, "chat-err")
    run4 = await runtime.start_run(thread_id=thread4, instruction="在吗")
    events = await collect(agent_stream(
        inform=AgentRequest(user_input="在吗", chat_thread_id=thread4),
        graph=graph, run=run4, runtime=runtime,
    ))
    check("done=failed", events[-1] == {"type": "done", "status": "failed"}, str(events[-1]))
    err = next((e for e in events if e["type"] == "error"), {})
    check("error code=graph_error", err.get("code") == "graph_error", str(err.get("code")))
    check("task FAILED", await task_status(factory, run4.task_id) == TaskStatus.FAILED.value,
          str(await task_status(factory, run4.task_id)))

    # ═══ 5. CODE 图执行异常 ═══
    print("\n=== 5. CODE 图异常 → failed ===")
    supervisor_mod.intent_llm = StreamingFake(text=json.dumps({"intent": "CODE"}))
    coder_mod.llm_with_tools = RaisingModel()
    thread5 = await new_thread(factory, user_id, "code-err")
    run5 = await runtime.start_run(thread_id=thread5, instruction="改代码")
    events = await collect(agent_stream(
        inform=AgentRequest(user_input="改代码", chat_thread_id=thread5),
        graph=graph, run=run5, runtime=runtime,
    ))
    check("done=failed", events[-1] == {"type": "done", "status": "failed"}, str(events[-1]))
    check("task FAILED", await task_status(factory, run5.task_id) == TaskStatus.FAILED.value,
          str(await task_status(factory, run5.task_id)))

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

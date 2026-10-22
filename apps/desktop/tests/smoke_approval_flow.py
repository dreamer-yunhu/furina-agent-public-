"""coder 子图审批链路冒烟测试（阶段 2 / 链路修复验收）。

跑法（仓库根）：
    .venv-build\\Scripts\\python.exe apps\\desktop\\tests\\smoke_approval_flow.py

它验的是**真实图 + 真实工具 + 真实 interrupt/resume**：
    1. 安全工具直接执行，不进审批
    2. 高风险工具停在 interrupt，载荷含 path/diff
    3. 批准后文件真的出现
    4. 拒绝后文件真的不出现，且模型收到打回消息
    5. 未知工具被拦下
    6. 路径越界被拦下

**唯一被 stub 的是 LLM**（它需要网络和密钥）；模型输出用 FakeModel 固定。
所以这不是"模拟审批"，审批链路本身是真实的。
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
import furina_desktop.agent.nodes.coder as coder_mod  # noqa: E402
from furina_desktop.agent.build import build_graph  # noqa: E402
from furina_desktop.agent.tools.registry import read_file_tool, write_file_tool  # noqa: E402

PASS, FAIL = "PASS", "FAIL"
_results: list[tuple[str, bool]] = []


def check(label: str, ok: bool, extra: str = "") -> None:
    _results.append((label, ok))
    print(f"  [{PASS if ok else FAIL}] {label}" + (f"   {extra}" if extra else ""))


class FakeModel:
    """只替代 LLM：第一次产出指定 tool_calls，之后产出最终文本。

    同时记录它最后一次看到的 ToolMessage —— 用来断言"模型到底收到了什么"。
    """

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


def sandbox() -> Path:
    path = ROOT / "_smoke_tmp" / "approval_sandbox"
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)
    path.mkdir(parents=True, exist_ok=True)
    settings.sandbox_root = path
    read_file_tool.root_dir = str(path)
    write_file_tool.root_dir = str(path)
    return path


async def run_case(name: str, tool_calls: list[dict], resume: dict | None = None):
    """跑一个独立 thread，返回 (graph, config, fake, 首次结果)。"""
    fake = FakeModel(tool_calls)
    coder_mod.llm_with_tools = fake
    graph = build_graph(InMemorySaver())
    config = {"configurable": {"thread_id": name}}
    first = await graph.ainvoke(
        {
            "messages": [HumanMessage(content="执行任务")],
            "mode": "code",
            "subagent_task": "执行任务",
        },
        config,
    )
    if resume is not None:
        await graph.ainvoke(Command(resume=resume), config)
    return graph, config, fake, first


async def main() -> None:
    box = sandbox()
    print("=== 1. 安全工具：读文件，不进审批 ===")
    (box / "readme.txt").write_text("hello-furina", encoding="utf-8")
    _, _, fake, _ = await run_case(
        "t-safe",
        [{"name": "read_file_tool", "args": {"file_path": "readme.txt"}, "id": "call_r1"}],
    )
    check("安全工具未触发 interrupt", fake.calls >= 2)
    got = "".join(str(m.content) for m in fake.seen_tool_messages)
    check("模型收到读取结果", "hello-furina" in got, got[:60])

    print("\n=== 2. 高风险工具：批准后写入 ===")
    graph, config, fake, first = await run_case(
        "t-approve",
        [{"name": "write_file_tool", "args": {"file_path": "out.txt", "text": "approved!"}, "id": "call_w1"}],
    )
    state = await graph.aget_state(config)
    check("图停在 interrupt", len(state.interrupts) == 1)
    payload = state.interrupts[0].value if state.interrupts else {}
    check("载荷含 approval 对象", bool(payload.get("requests")), str(payload)[:80])
    if payload.get("requests"):
        req = payload["requests"][0]
        check("载荷绑定路径", req.get("path") == "out.txt")
        check("载荷含 diff", "approved!" in (req.get("diff") or ""))

    await graph.ainvoke(
        Command(
            resume={
                "type": "review_decision",
                "decisions": [{"tool_call_id": "call_w1", "action": "approve", "reason": None}],
            }
        ),
        config,
    )
    check("批准后文件出现", (box / "out.txt").is_file())
    check("文件内容正确", (box / "out.txt").read_text(encoding="utf-8") == "approved!")

    print("\n=== 3. 高风险工具：拒绝后不写入 ===")
    graph, config, fake, _ = await run_case(
        "t-reject",
        [{"name": "write_file_tool", "args": {"file_path": "denied.txt", "text": "nope"}, "id": "call_w2"}],
        resume={
            "type": "review_decision",
            "decisions": [{"tool_call_id": "call_w2", "action": "reject", "reason": "不允许"}],
        },
    )
    check("拒绝后文件不存在", not (box / "denied.txt").exists())
    got = "".join(str(m.content) for m in fake.seen_tool_messages)
    check("模型收到拒绝消息", "拒绝" in got, got[:80])

    print("\n=== 4. 未知工具：拦下并回填错误 ===")
    graph, config, fake, _ = await run_case(
        "t-unknown",
        [{"name": "hack_tool", "args": {}, "id": "call_x1"}],
    )
    state = await graph.aget_state(config)
    check("未知工具不进入 interrupt", len(state.interrupts) == 0)
    got = "".join(str(m.content) for m in fake.seen_tool_messages)
    check("模型收到未知工具提示", "未知工具" in got, got[:80])

    print("\n=== 5. 路径越界：拦下且不写沙箱外 ===")
    outside = box.parent / "escape.txt"
    if outside.exists():
        outside.unlink()
    graph, config, fake, _ = await run_case(
        "t-escape",
        [{"name": "write_file_tool", "args": {"file_path": "../escape.txt", "text": "x"}, "id": "call_e1"}],
    )
    state = await graph.aget_state(config)
    check("越界不进入 interrupt", len(state.interrupts) == 0)
    check("沙箱外文件未创建", not outside.exists())
    got = "".join(str(m.content) for m in fake.seen_tool_messages)
    check("模型收到载荷构造失败", "审批载荷构造失败" in got, got[:100])

    ok = sum(1 for _, o in _results if o)
    print(f"\n{ok}/{len(_results)} 通过")
    if ok != len(_results):
        print("失败项:")
        for label, o in _results:
            if not o:
                print("  -", label)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())

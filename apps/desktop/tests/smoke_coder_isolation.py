"""T13 冒烟：coder 子图每轮是白纸，但同一轮内的 ReAct 历史要保留。

# ── AI-ASSISTED ── 本文件由 AI 生成，待人工复核 ──
# 复核重点：断言看的是"模型实际收到的消息列表"，不是 state 字段本身。
# 如果哪天 prepare_node 的清空被移走，这里会先红。

跑法（仓库根）：
    .venv-build\\Scripts\\python.exe apps\\desktop\\tests\\smoke_coder_isolation.py
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

from furina_core.config import settings  # noqa: E402
import furina_desktop.agent.nodes.coder as coder_mod  # noqa: E402
from furina_desktop.agent.build import build_graph  # noqa: E402
from furina_desktop.agent.tools.registry import read_file_tool, write_file_tool  # noqa: E402
from _t23_testkit import install_intent  # noqa: E402  Stage A：主管意图节点也要替身

PASS, FAIL = "PASS", "FAIL"
_results: list[tuple[str, bool]] = []


def check(label: str, ok: bool, extra: str = "") -> None:
    _results.append((label, ok))
    print(f"  [{PASS if ok else FAIL}] {label}" + (f"   {extra}" if extra else ""))


class ScriptedModel:
    """按脚本依次返回响应，并记录每次调用收到的完整消息列表。"""

    def __init__(self, responses: list[AIMessage]) -> None:
        self.responses = list(responses)
        self.inputs: list[list] = []

    async def ainvoke(self, messages):
        self.inputs.append(list(messages))
        return self.responses.pop(0)


def humans(messages) -> list[str]:
    return [m.content for m in messages if isinstance(m, HumanMessage)]


def has_text(messages, needle: str) -> bool:
    return any(needle in str(m.content) for m in messages)


async def main() -> None:
    box = ROOT / "_smoke_tmp" / "coder_isolation"
    if box.exists():
        shutil.rmtree(box, ignore_errors=True)
    box.mkdir(parents=True, exist_ok=True)
    (box / "readme.txt").write_text("hello-isolation", encoding="utf-8")
    settings.sandbox_root = box
    read_file_tool.root_dir = str(box)
    write_file_tool.root_dir = str(box)

    fake = ScriptedModel([
        AIMessage(content="done-A"),                                   # 第 1 轮：直接结束
        AIMessage(content="", tool_calls=[{                            # 第 2 轮：先读文件
            "name": "read_file_tool",
            "args": {"file_path": "readme.txt"},
            "id": "call_r1",
        }]),
        AIMessage(content="done-B"),                                   # 第 2 轮：收尾
        AIMessage(content="done-C"),                                   # 第 3 轮：直接结束
    ])
    coder_mod.llm_with_tools = fake
    install_intent("CODE")  # <- AI 改动（Stage A）：测试不联网
    graph = build_graph(InMemorySaver())
    config = {"configurable": {"thread_id": "t13-isolation"}}

    async def run(task: str) -> None:
        # <- AI 改动（Stage A）：入口只给 task_input，意图 → 子图字段由校验节点映射
        await graph.ainvoke(
            {"messages": [HumanMessage(content=task)], "task_input": task,
             "intent_attempts": 0},
            config,
        )

    await run("task A")
    await run("task B")
    await run("task C")

    check("model called 4 times", len(fake.inputs) == 4, f"n={len(fake.inputs)}")

    # 第 2 轮第一次调用 = inputs[1]
    second_first = fake.inputs[1]
    check("round 2 starts from a clean slate", humans(second_first) == ["task B"],
          str(humans(second_first)))
    check("round 2 no longer sees round 1", not has_text(second_first, "task A"))

    # 第 2 轮第二次调用 = inputs[2]，同一轮内的工具结果必须还在
    second_second = fake.inputs[2]
    check("same-round tool history preserved",
          any(isinstance(m, ToolMessage) for m in second_second))
    check("same-round tool result readable", has_text(second_second, "hello-isolation"))

    # 第 3 轮第一次调用 = inputs[3]
    third_first = fake.inputs[3]
    check("round 3 starts clean", humans(third_first) == ["task C"], str(humans(third_first)))

    # <- AI 新增（核验回归）：同一 thread 跑三轮，意图重试计数必须每轮归零。
    #    不归零的话第 3 轮一开始就吃掉 2 次预算，非法输出的重试会直接失效。
    snap = await graph.aget_state(config)
    check("intent_attempts reset per run", (snap.values or {}).get("intent_attempts") == 1,
          str((snap.values or {}).get("intent_attempts")))
    check("round 3 sees neither A nor B",
          not has_text(third_first, "task A") and not has_text(third_first, "task B"))

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

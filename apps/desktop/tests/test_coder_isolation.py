# ── AI-ASSISTED ── 本文件由 AI 生成，待人工复核 ──
"""coder 子图轮次隔离（由 smoke_coder_isolation.py 原生化）。

复核重点：
    断言看的是**模型实际收到的消息列表**，不是 state 字段本身 ——
    如果哪天 prepare_node 的清空被移走，这里会先红。

原脚本用 `_smoke_tmp/` + 手写 check；这里用 `tmp_path` 和 assert。
异步部分用 `asyncio.run` 包起来，不引入 pytest-asyncio 插件。
"""

from __future__ import annotations

import asyncio

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver

import furina_desktop.agent.nodes.coder as coder_mod
from _t23_testkit import install_intent
from furina_core.config import settings
from furina_desktop.agent.build import build_graph
from furina_desktop.agent.tools.registry import read_file_tool, write_file_tool


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


@pytest.fixture()
def coder_env(tmp_path):
    box = tmp_path / "sandbox"
    box.mkdir()
    (box / "readme.txt").write_text("hello-isolation", encoding="utf-8")

    settings.sandbox_root = box
    read_file_tool.root_dir = str(box)
    write_file_tool.root_dir = str(box)

    fake = ScriptedModel(
        [
            AIMessage(content="done-A"),  # 第 1 轮：直接结束
            AIMessage(  # 第 2 轮：先读文件
                content="",
                tool_calls=[
                    {
                        "name": "read_file_tool",
                        "args": {"file_path": "readme.txt"},
                        "id": "call_r1",
                    }
                ],
            ),
            AIMessage(content="done-B"),  # 第 2 轮：收尾
            AIMessage(content="done-C"),  # 第 3 轮：直接结束
        ]
    )
    coder_mod.llm_with_tools = fake
    install_intent("CODE")
    graph = build_graph(InMemorySaver())
    config = {"configurable": {"thread_id": "t13-isolation"}}
    return fake, graph, config


def test_coder_rounds_are_isolated_but_tool_history_is_kept(coder_env):
    fake, graph, config = coder_env

    async def run(task: str) -> None:
        await graph.ainvoke(
            {"messages": [HumanMessage(content=task)], "task_input": task},
            config,
        )

    asyncio.run(run("task A"))
    asyncio.run(run("task B"))
    asyncio.run(run("task C"))

    assert len(fake.inputs) == 4, f"模型调用次数 n={len(fake.inputs)}"

    # 第 2 轮第一次调用 = inputs[1]：必须是白纸
    second_first = fake.inputs[1]
    assert humans(second_first) == ["task B"], humans(second_first)
    assert not has_text(second_first, "task A"), "第 2 轮仍能看到第 1 轮"

    # 第 2 轮第二次调用 = inputs[2]：同一轮内的工具结果必须还在
    second_second = fake.inputs[2]
    assert any(isinstance(m, ToolMessage) for m in second_second), "同一轮工具历史丢失"
    assert has_text(second_second, "hello-isolation"), "同一轮工具结果不可读"

    # 第 3 轮第一次调用 = inputs[3]
    third_first = fake.inputs[3]
    assert humans(third_first) == ["task C"], humans(third_first)
    assert not has_text(third_first, "task A") and not has_text(third_first, "task B")

    async def snapshot():
        return await graph.aget_state(config)

    snap = asyncio.run(snapshot())
    # 意图重试计数必须每轮归零：不归零的话第 3 轮一开始就吃掉预算
    assert (snap.values or {}).get("intent_attempts") == 1, (
        snap.values or {}
    ).get("intent_attempts")

# ── AI-ASSISTED ── 本文件由 AI 生成，待人工复核 ──
"""pytest 夹具：真 lifespan + 真 SQLite + 假模型。

设计依据（照抄 `smoke_http_resume.py` 已验证过的做法）：
    1. **先 chdir 再 create_app** —— 业务库与 checkpoint 都是相对 CWD 的路径，
       否则测试会写到仓库根的 data/。
    2. 意图节点必须装替身（`_t23_testkit.install_intent`），否则会真连模型。
    3. coder 子图的模型换成分块输出的假模型：第一次调用产出一个
       write_file_tool 调用（触发审批），第二次调用输出结束语。

复核重点：
    · `os.chdir` 是**进程级**副作用，所以必须在 finally 里还原；
    · 夹具是按用例新建 app 的，模块级变量（llm_with_tools / intent_llm）
      每个用例都会被重新赋值，不依赖上一个用例的残留。
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult

ROOT = Path(__file__).resolve().parents[3]
for extra in (
    ROOT / "apps" / "desktop" / "src",
    ROOT / "packages" / "core" / "src",
    ROOT / "apps" / "desktop" / "tests",
):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))


class FakeToolModel(BaseChatModel):
    """第一次调用产出 write_file_tool，之后输出结束语。"""

    calls: int = 0

    @property
    def _llm_type(self) -> str:
        return "fake-tool"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        self.calls += 1
        if self.calls == 1:
            message = AIMessage(
                content="好的，",
                tool_calls=[
                    {
                        "name": "write_file_tool",
                        "args": {"file_path": "out.txt", "text": "approved!"},
                        "id": "call_w1",
                    }
                ],
            )
        else:
            message = AIMessage(content="done")
        return ChatResult(generations=[ChatGeneration(message=message)])

    async def _astream(self, messages, stop=None, run_manager=None, **kwargs):
        self.calls += 1
        if self.calls == 1:
            for piece in ("好", "的", "，"):
                yield ChatGenerationChunk(message=AIMessageChunk(content=piece))
            yield ChatGenerationChunk(
                message=AIMessageChunk(
                    content="",
                    tool_call_chunks=[
                        {
                            "name": "write_file_tool",
                            "args": json.dumps(
                                {"file_path": "out.txt", "text": "approved!"}
                            ),
                            "id": "call_w1",
                            "index": 0,
                        }
                    ],
                )
            )
        else:
            for piece in ("do", "ne"):
                yield ChatGenerationChunk(message=AIMessageChunk(content=piece))
        yield ChatGenerationChunk(message=AIMessageChunk(content=""))


@pytest.fixture()
def app_client(tmp_path):
    """隔离环境下的 TestClient。同时暴露 sandbox 目录给需要断言的用例。"""
    workdir = tmp_path
    (workdir / "data").mkdir()
    sandbox = workdir / "sandbox"
    sandbox.mkdir()

    previous_cwd = os.getcwd()
    os.chdir(workdir)
    try:
        from fastapi.testclient import TestClient

        import furina_desktop.agent.nodes.coder as coder_mod
        from _t23_testkit import install_intent
        from furina_core.config import settings
        from furina_desktop.agent.tools.registry import read_file_tool, write_file_tool
        from furina_desktop.main import create_app

        settings.sandbox_root = sandbox
        read_file_tool.root_dir = str(sandbox)
        write_file_tool.root_dir = str(sandbox)
        install_intent("CODE")
        coder_mod.llm_with_tools = FakeToolModel()

        app = create_app()
        with TestClient(app) as client:
            client.sandbox = sandbox  # type: ignore[attr-defined]
            yield client
    finally:
        os.chdir(previous_cwd)

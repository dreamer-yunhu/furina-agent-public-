# ── AI-ASSISTED ── 本文件由 AI 生成，待人工复核 ──
"""工具安全与健壮性（由 smoke_tool_safety.py 原生化）。

复核重点：
    第 3~6 组断言的是**模型看到的文本**，不是日志 —— 目的是防止绝对路径
    再次进入模型上下文。改写时保持了原文的判定口径（"不存在"/"目录"/"UTF-8"）。

原脚本使用 `_smoke_tmp/` + 手写 check；这里换成 pytest 的 `tmp_path`，
每个用例独立目录，失败时 pytest 会直接指出是哪个断言。
"""

from __future__ import annotations

import asyncio

import pytest

from furina_desktop.agent.dependencies import build_write_review
from furina_desktop.agent.tools.coder_tools import (
    ReadFileTool,
    WriteFileTool,
    _safe_error_message,
)
from furina_desktop.agent.tools.path_jail import ensure_sandbox_root


def leaks_absolute(text: str, box) -> bool:
    return "C:\\" in text or str(box) in text or str(box).replace("\\", "/") in text


@pytest.fixture()
def box(tmp_path):
    """沙箱根：由 ensure_sandbox_root 创建（顺带覆盖"自动建目录"）。"""
    return ensure_sandbox_root(tmp_path / "a" / "b" / "sandbox")


def test_ensure_sandbox_root_creates_and_is_idempotent(tmp_path):
    nested = tmp_path / "a" / "b" / "sandbox"
    assert not nested.exists()
    created = ensure_sandbox_root(nested)
    assert created.is_dir() and created == nested.resolve()
    assert ensure_sandbox_root(nested) == created


def test_write_creates_missing_parent_directories(box):
    writer = WriteFileTool(root_dir=str(box))
    result = writer._run("sub/dir/note.txt", "hello-parent")
    assert "成功" in result, result
    target = box / "sub" / "dir" / "note.txt"
    assert target.is_file()
    assert target.read_text(encoding="utf-8") == "hello-parent"


def test_missing_file_message_is_sanitized(box):
    message = ReadFileTool(root_dir=str(box))._run("nope.txt")
    assert "不存在" in message, message
    assert "nope.txt" in message
    assert not leaks_absolute(message, box), message


def test_reading_directory_is_explicit(box):
    (box / "adir").mkdir()
    message = ReadFileTool(root_dir=str(box))._run("adir")
    assert "目录" in message, message
    assert not leaks_absolute(message, box), message


def test_writing_onto_directory_is_explicit(box):
    (box / "adir").mkdir()
    message = WriteFileTool(root_dir=str(box))._run("adir", "x")
    assert "目录" in message, message
    assert (box / "adir").is_dir()
    assert not leaks_absolute(message, box), message


def test_non_utf8_message_is_sanitized(box):
    (box / "bin.dat").write_bytes(b"\xff\xfe\x00abc")
    message = ReadFileTool(root_dir=str(box))._run("bin.dat")
    assert "UTF-8" in message, message
    assert not leaks_absolute(message, box), message


def test_traversal_still_blocked_and_creates_nothing_outside(box):
    outside = box.parent / "escape_dir"
    message = WriteFileTool(root_dir=str(box))._run("../escape_dir/x.txt", "x")
    assert "超出可操作范围" in message, message
    assert not outside.exists()


def test_unknown_exception_keeps_only_type_name():
    message = _safe_error_message(
        exc=RuntimeError("C:\\secret\\path.txt"), rel_path="rel.txt"
    )
    assert "secret" not in message, message
    assert "RuntimeError" in message, message


def test_approval_payload_lists_directories_to_create(box):
    def review_for(file_path: str):
        return asyncio.run(
            build_write_review(
                tool_call={
                    "id": "call_t34",
                    "args": {"file_path": file_path, "text": "x"},
                },
                workspace_root=box,
            )
        )

    nested = review_for("deep/a/note.txt")
    assert nested.creates_dirs == ["deep", "deep/a"], nested.creates_dirs
    assert nested.model_dump().get("creates_dirs") == ["deep", "deep/a"]

    (box / "ready").mkdir()
    assert review_for("ready/x.txt").creates_dirs == []

    (box / "existing.txt").write_text("old", encoding="utf-8")
    existing = review_for("existing.txt")
    assert existing.creates_dirs == []
    assert existing.is_new_file is False

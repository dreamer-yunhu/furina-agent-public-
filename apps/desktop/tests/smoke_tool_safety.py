"""工具安全与健壮性冒烟：沙箱根自动创建 / 父目录 / 错误措辞不泄漏绝对路径。

# ── AI-ASSISTED ── 本文件由 AI 生成，待人工复核 ──
# 复核重点：第 3~6 条断言的是"模型看到的文本"，不是日志。
# 目的是防止绝对路径再次进入模型上下文。

跑法（仓库根）：
    .venv-build\\Scripts\\python.exe apps\\desktop\\tests\\smoke_tool_safety.py
"""
from __future__ import annotations

import asyncio
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "apps" / "desktop" / "src"))
sys.path.insert(0, str(ROOT / "packages" / "core" / "src"))

from furina_desktop.agent.dependencies import build_write_review  # noqa: E402
from furina_desktop.agent.tools.coder_tools import ReadFileTool, WriteFileTool, _safe_error_message  # noqa: E402
from furina_desktop.agent.tools.path_jail import ensure_sandbox_root  # noqa: E402

PASS, FAIL = "PASS", "FAIL"
_results: list[tuple[str, bool]] = []


def check(label: str, ok: bool, extra: str = "") -> None:
    _results.append((label, ok))
    print(f"  [{PASS if ok else FAIL}] {label}" + (f"   {extra}" if extra else ""))


def leaks_absolute(text: str, box: Path) -> bool:
    return "C:\\" in text or str(box) in text or str(box).replace("\\", "/") in text


def main() -> None:
    base = ROOT / "_smoke_tmp" / "tool_safety"
    if base.exists():
        shutil.rmtree(base, ignore_errors=True)

    print("=== 1. ensure_sandbox_root creates missing directory ===")
    nested = base / "a" / "b" / "sandbox"
    check("dir absent before", not nested.exists())
    created = ensure_sandbox_root(nested)
    check("dir created", created.is_dir() and created == nested.resolve())
    check("idempotent", ensure_sandbox_root(nested) == created)

    box = created
    reader = ReadFileTool(root_dir=str(box))
    writer = WriteFileTool(root_dir=str(box))

    print("\n=== 2. write creates missing parent directories ===")
    result = writer._run("sub/dir/note.txt", "hello-parent")
    check("write reports success", "成功" in result, result)
    target = box / "sub" / "dir" / "note.txt"
    check("file exists", target.is_file())
    check("content correct", target.read_text(encoding="utf-8") == "hello-parent")

    print("\n=== 3. missing file message is sanitized ===")
    msg = reader._run("nope.txt")
    check("says not found", "不存在" in msg, msg)
    check("uses relative path", "nope.txt" in msg)
    check("no absolute path leaked", not leaks_absolute(msg, box), msg)

    print("\n=== 4. reading a directory is explicit ===")
    (box / "adir").mkdir(exist_ok=True)
    msg = reader._run("adir")
    check("says it is a directory", "目录" in msg, msg)
    check("no absolute path leaked", not leaks_absolute(msg, box), msg)

    print("\n=== 5. writing onto a directory is explicit ===")
    msg = writer._run("adir", "x")
    check("says it is a directory", "目录" in msg, msg)
    check("directory untouched", (box / "adir").is_dir())
    check("no absolute path leaked", not leaks_absolute(msg, box), msg)

    print("\n=== 6. non-UTF8 file message is sanitized ===")
    (box / "bin.dat").write_bytes(b"\xff\xfe\x00abc")
    msg = reader._run("bin.dat")
    check("mentions UTF-8", "UTF-8" in msg, msg)
    check("no absolute path leaked", not leaks_absolute(msg, box), msg)

    print("\n=== 7. traversal still blocked, no dirs created outside ===")
    outside = box.parent / "escape_dir"
    if outside.exists():
        shutil.rmtree(outside)
    msg = writer._run("../escape_dir/x.txt", "x")
    check("rejected as out of sandbox", "超出可操作范围" in msg, msg)
    check("nothing created outside", not outside.exists())

    print("\n=== 8. unknown exception keeps only the type name ===")
    msg = _safe_error_message(exc=RuntimeError("C:\\secret\\path.txt"), rel_path="rel.txt")
    check("no message body leaked", "secret" not in msg, msg)
    check("type name kept", "RuntimeError" in msg, msg)

    print("\n=== 9. approval payload lists directories it will create (T34) ===")

    def review_for(file_path: str):
        return asyncio.run(build_write_review(
            tool_call={"id": "call_t34", "args": {"file_path": file_path, "text": "x"}},
            workspace_root=box,
        ))

    nested_preview = review_for("deep/a/note.txt")
    check("lists missing dirs shallow -> deep",
          nested_preview.creates_dirs == ["deep", "deep/a"], str(nested_preview.creates_dirs))
    check("field survives serialization",
          nested_preview.model_dump().get("creates_dirs") == ["deep", "deep/a"])

    (box / "ready").mkdir(exist_ok=True)
    check("no dirs when parent exists", review_for("ready/x.txt").creates_dirs == [])

    (box / "existing.txt").write_text("old", encoding="utf-8")
    existing_preview = review_for("existing.txt")
    check("no dirs for existing file", existing_preview.creates_dirs == [])
    check("existing file not marked new", existing_preview.is_new_file is False)

    ok = sum(1 for _, o in _results if o)
    print(f"\n{ok}/{len(_results)} passed")
    if ok != len(_results):
        print("failed:")
        for label, o in _results:
            if not o:
                print("  -", label)
        sys.exit(1)


if __name__ == "__main__":
    main()

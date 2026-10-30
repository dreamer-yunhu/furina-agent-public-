# ── AI-ASSISTED ── 本文件由 AI 生成，待人工复核 ──
"""遗留冒烟脚本的 pytest 桥接（**过渡态**，不是终态）。

背景：`tests/` 下有 17 个 `smoke_*.py`，它们各自 `main()` + 手写 `check()`
+ 失败 `sys.exit(1)`，pytest 收集不到 —— 等于游离在统一入口之外。

这里做两件事：
    1. 每个脚本自动生成一个 pytest 用例，断言退出码为 0 —— 让 `pytest`
       成为唯一入口，脚本失败会直接让套件红。
    2. 脚本被逐个原生化（如已完成的 `test_tool_safety.py`）并从目录删除后，
       参数列表自动变短，**不需要改这个文件**。

为什么不一次性重写：17 个脚本约 5000 行、586 处断言，且各自有独立夹具
（临时库 / 假模型 / chdir）。逐个原生化风险更低；先保证"能统一跑、失败可见"，
再按 `docs/TODO.md` 的顺序迁移。

复核重点：
    · 子进程在**仓库根**启动（脚本自己会 chdir）；
    · 超时给 300s：`smoke_timeout_scanner` 这类含等待的脚本最慢；
    · 失败时把脚本 stdout 尾部带进断言消息，否则只能看到 "exit 1"。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

TESTS_DIR = Path(__file__).resolve().parent
REPO_ROOT = TESTS_DIR.parents[2]

SMOKE_SCRIPTS = sorted(path.name for path in TESTS_DIR.glob("smoke_*.py"))


@pytest.mark.parametrize("script", SMOKE_SCRIPTS)
def test_legacy_smoke(script: str) -> None:
    completed = subprocess.run(
        [sys.executable, str(TESTS_DIR / script)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert completed.returncode == 0, (
        f"{script} 退出码 {completed.returncode}\n"
        f"--- stdout (tail) ---\n{completed.stdout[-3000:]}\n"
        f"--- stderr (tail) ---\n{completed.stderr[-2000:]}"
    )

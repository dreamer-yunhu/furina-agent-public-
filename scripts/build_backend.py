# ── AI-ASSISTED ── 本文件由 AI 生成，待人工复核 ──
"""把桌面版 Python 后端打成单个 exe（T4）。

用法（仓库根目录）：

    uv sync --all-packages          # 首次/依赖变更后：**必须带 --all-packages**
    .venv\\Scripts\\python.exe scripts\\build_backend.py

⚠️ 别用裸 `uv sync`：它只同步根项目，会把 workspace 成员
（furina_desktop / furina_core）从环境里卸掉，随后 import 直接失败。
也不要在 npm script 里用 `uv run`，同理。

产物：
  · `dist-backend/furina-backend.exe`
  · 自动复制到 `apps/desktop/src/frontend/src-tauri/binaries/`，供安装包内置

═══════════════════════════════════════════════════════════════════════
为什么需要这些参数（每一条都是踩过或已知会踩的）
═══════════════════════════════════════════════════════════════════════

1. `--add-data ...prompts;furina_desktop/agent/prompts`
   loader.py 用 `Path(__file__).parent` 找 .txt。PyInstaller 会把模块塞进
   PYZ 归档，`__file__` 指向 `_MEIPASS/furina_desktop/...`；**不把 .txt
   放到同一个相对路径下，打包后第一次对话就会 PromptNotFound**。
   这个故障在开发环境永远复现不了。

2. `--collect-submodules uvicorn`
   uvicorn 用字符串动态导入 `uvicorn.loops.auto` / `uvicorn.protocols.*`，
   PyInstaller 的静态分析看不到。

3. `--hidden-import aiosqlite` + `sqlalchemy.dialects.sqlite.aiosqlite`
   SQLAlchemy 的方言同样是运行时按 URL 拼字符串导入的。

4. `--exclude-module lancedb/pyarrow/...`
   desktop 的 pyproject 里列了 lancedb（M2 的 RAG 才用），但启动路径
   **不 import 它**；不排除的话包体积会翻好几倍。

5. `--onefile`
   先求"能跑通"。onefile 每次启动要把内容解到临时目录，冷启动会慢；
   真到了体验阶段再换 onedir（目录形态，启动快，但要改 Tauri 的资源布局）。

复核重点：
  · 打包成功 ≠ 能跑。必须实测：起 exe → /healthz → 发一条真消息。
  · 首次构建建议加 `--log-level WARN` 看缺了哪些隐式依赖。
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
NAME = "furina-backend"
DIST = REPO / "dist-backend"
WORK = REPO / "build-backend"

# 提示词目录：相对路径必须和包内结构一致（见上面第 1 条）
PROMPTS_SRC = REPO / "apps" / "desktop" / "src" / "furina_desktop" / "agent" / "prompts"
PROMPTS_DEST = "furina_desktop/agent/prompts"

EXCLUDES = [
    "lancedb",
    "pyarrow",
    "pandas",
    "matplotlib",
    "tkinter",
    "IPython",
    "pytest",
    "PyInstaller",
]


def main() -> int:
    if not PROMPTS_SRC.is_dir():
        print(f"[FAIL] 提示词目录不存在: {PROMPTS_SRC}")
        return 1

    for path in (DIST, WORK):
        if path.exists():
            shutil.rmtree(path, ignore_errors=True)

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--console",
        "--name",
        NAME,
        "--distpath",
        str(DIST),
        "--workpath",
        str(WORK),
        "--specpath",
        str(WORK),
        "--add-data",
        f"{PROMPTS_SRC}{';' if sys.platform == 'win32' else ':'}{PROMPTS_DEST}",
        "--collect-submodules",
        "uvicorn",
        "--hidden-import",
        "aiosqlite",
        "--hidden-import",
        "sqlalchemy.dialects.sqlite.aiosqlite",
        "--hidden-import",
        "langgraph.checkpoint.sqlite",
        "--hidden-import",
        "langgraph.checkpoint.sqlite.aio",
    ]
    for module in EXCLUDES:
        cmd += ["--exclude-module", module]
    cmd.append(str(REPO / "scripts" / "backend_entry.py"))

    print("[build] " + " ".join(cmd))
    result = subprocess.run(cmd, cwd=REPO)
    if result.returncode != 0:
        print(f"[FAIL] PyInstaller 退出码 {result.returncode}")
        return result.returncode

    exe = DIST / f"{NAME}.exe"
    if not exe.is_file():
        print(f"[FAIL] 未生成 {exe}")
        return 1
    print(f"[OK] {exe} ({exe.stat().st_size / 1048576:.1f} MiB)")

    # 复制进 Tauri 的 bundle.resources，安装包才会带上它。
    # 目录名 `binaries` 与 tauri.conf.json 里的 resources 路径必须一致。
    target = REPO / "apps" / "desktop" / "src" / "frontend" / "src-tauri" / "binaries"
    target.mkdir(parents=True, exist_ok=True)
    shutil.copy2(exe, target / f"{NAME}.exe")
    print(f"[OK] 已复制到 {target / f'{NAME}.exe'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

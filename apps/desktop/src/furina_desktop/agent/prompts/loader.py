"""提示词加载 —— 集中到一处，杜绝硬编码路径。

═══════════════════════════════════════════════════════════════════════
为什么需要这个文件（它修的是一个真 bug）
═══════════════════════════════════════════════════════════════════════

原 `coder.py` 的 `model_node` 里是这么读提示词的：

    with open("C:/furina-agent/backend/app/prompt/coder.txt", ...)

**三个问题叠在一起**：
    ① **绝对路径写死在源码里** → 换机器、别人 clone、打包成安装包，全部炸
    ② 在 **async 函数里做同步 IO** → 阻塞事件循环（读一个小文件影响不大，但这是坏习惯）
    ③ **每次调用都读一遍磁盘** → 模型节点是循环里最热的路径

本模块一次解决三个：路径基于 `__file__` 推导、内容缓存、提供同步与异步两个入口。

═══════════════════════════════════════════════════════════════════════
路径为什么用 __file__ 而不是工作目录
═══════════════════════════════════════════════════════════════════════

    工作目录（CWD）：由"用户从哪儿启动程序"决定 —— 双击图标、命令行、IDE 调试
                     三个场景各不相同 → 相对路径必然出错
    __file__：       由"这个 .py 文件装在哪"决定 → 打包后依然正确

**判据**：凡是"包内自带的资源文件"，路径一律从 `__file__` 推导。
"""

# ── AI-ASSISTED ── 本文件由 AI 生成/改写，待人工复核 ──
# 复核重点：
#   1. 提示词文件现在是 agent/prompts/*.txt，**和包一起走**。
#      打包时 `uv_build` 默认**只带 .py** —— .txt 需要额外配置（见文末说明）。
#      这是让 smoke 测试能过、但打包后崩掉的典型陷阱，务必验。
#   2. 缓存用了模块级 dict。开发时改 .txt 不会生效（要重启进程）。
#      如果嫌烦，可以加个 `reload=True` 参数，我留给你决定。

from __future__ import annotations

import asyncio
from pathlib import Path

_PROMPT_DIR = Path(__file__).resolve().parent

# 文件名 → 内容。避免每次调用都读盘。
_cache: dict[str, str] = {}


class PromptNotFound(FileNotFoundError):
    """提示词文件缺失。

    ⚠️ 单独定义这个异常，是为了让错误信息**可操作**：
       打包后最常见的故障就是"提示词没被打进包里"，
       而原始的 `FileNotFoundError` 只会说"找不到文件"，看不出是这个原因。
    """


def prompt_path(name: str) -> Path:
    """返回提示词文件的绝对路径（不检查存在性）。

    `name` 可以带或不带 `.txt` 后缀。
    """
    filename = name if name.endswith(".txt") else f"{name}.txt"
    return _PROMPT_DIR / filename


def load_prompt(name: str) -> str:
    """读取提示词（带缓存）。同步版本。

    :raises PromptNotFound: 文件不存在，或（打包场景）没被包含进分发包
    """
    filename = name if name.endswith(".txt") else f"{name}.txt"
    cached = _cache.get(filename)
    if cached is not None:
        return cached

    path = _PROMPT_DIR / filename
    if not path.is_file():
        raise PromptNotFound(
            f"找不到提示词 {filename}（期望路径 {path}）。"
            "如果这是打包后的程序，说明 .txt 没有被包含进分发包 —— "
            "需要在构建配置里声明为非 Python 资源文件。"
        )
    text = path.read_text(encoding="utf-8")
    _cache[filename] = text
    return text


async def aload_prompt(name: str) -> str:
    """异步版本。

    命中缓存时**完全不碰磁盘**；未命中时用 `asyncio.to_thread` 把读盘丢到线程池，
    避免在事件循环里做阻塞 IO（节点函数是 async 的，这点很重要）。
    """
    filename = name if name.endswith(".txt") else f"{name}.txt"
    if filename in _cache:
        return _cache[filename]
    text = await asyncio.to_thread(load_prompt, filename)
    return text


def available() -> list[str]:
    """列出包里实际存在的提示词文件。用于启动时自检。"""
    return sorted(p.name for p in _PROMPT_DIR.glob("*.txt"))


def clear_cache() -> None:
    """清缓存。开发时改完 .txt 调它，或在测试里用。"""
    _cache.clear()


# ══════════════════════════════════════════════════════════════════════
# 打包注意（必读）
# ══════════════════════════════════════════════════════════════════════
#
# `uv_build` / setuptools / PyInstaller **默认都不会自动包含 .txt**。
# 本目录下的 coder.txt / supervisor.txt 等需要在构建配置里显式声明。
#
# 验证方法（打包后必须做）：
#     furina-desktop.exe --check-prompts
#     或在启动时调用 available()，断言列表非空
#
# 这是"本地能跑、打包后崩"的经典陷阱 —— M0 的打包实验必须覆盖它。

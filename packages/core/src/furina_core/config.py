"""配置基类 + 全局 `settings` 实例。

═══════════════════════════════════════════════════════════════════════
一、全局 settings 为什么放在 core
═══════════════════════════════════════════════════════════════════════

实测依赖分布（谁在用 settings）：

    base_url / api_key       desktop 的 LLM 客户端、web 的流式对话   → 两边都要
    search_api_key           desktop 的联网搜索工具                  → 只有 desktop
    sandbox_root             desktop 的文件工具                      → 只有 desktop
    pg_url / redis_url       web 的 Postgres / Redis                 → **只有 web**

前三个是"两边都可能要"的，所以全局 `settings` 放 core 是合理的。
**但 `pg_url` / `redis_url` 不放这里** —— 往共享内核里塞 web 私有配置，
会让 core 变成一个"什么都有"的垃圾桶（那正是重构前 `config.py` 的问题）。

web 的数据库配置在 `furina_web.config`（继承本文件，见那里的说明）。

═══════════════════════════════════════════════════════════════════════
二、为什么不在 import 期 raise（与原始实现的关键差异）
═══════════════════════════════════════════════════════════════════════

原 `backend/app/core/config.py` 在**模块顶层**做：

    if not API_KEY:        raise ValueError("API_KEY not set")
    if not SEARCH_API_KEY: raise ValueError("SEARCH_API_KEY not set")

后果：**不用搜索工具的人也无法启动** —— 那是开源分发的第一个坑
（`docs/PLAN.md` §九 自己把这条列为"必须先填的工程坑"）。

这里改成 `require_*()` 显式方法：**谁用谁检查**，启动时给可操作的错误。
"""

# ── AI-ASSISTED ── 本文件由 AI 生成/改写，待人工复核 ──
# 复核重点：
#   1. ★ 全局 `settings` 是 `CommonSettings` 实例。**空 API key 不再阻止导入**（见上面第二节）。
#      这是行为变更 —— 原实现"缺 key 就起不来"，现在"起得来，用到才报错"。
#   2. `WebSettings` 已从这里**移走**（去 `furina_web.config`）。
#      如果你觉得 web 配置也该留在 core（少一个文件），告诉我搬回来。
#   3. `sandbox_root` 用 `Path(os.getenv(...) or ".")` 兜底：
#      原来的 `Path(os.getenv("SANDBOX_ROOT"))` 在变量缺失时是 `Path(None)` → TypeError。
#      但**兜底成 "."（当前工作目录）在安全上很激进** —— 等于沙箱根 = 进程 CWD。
#      已标记为待办：DesktopSettings 必须显式提供它。

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv


def _find_dotenv() -> Path | None:
    """找 .env。开发态向上找 5 层；打包态（PyInstaller）按"用户配置优先"找。

    ⚠️ 这是启发式：在**开发时**很有用（跑测试不必手工设环境变量）。
    **打包后不能向上找** —— 冻结包的 `__file__` 指向临时解压目录
    （`%TEMP%\\_MEIxxxx`），沿父目录找只会找到临时目录。

    打包后（T4 实测踩过）按这个顺序：
      ① 可执行文件同级的 .env        —— 便携部署
      ② 当前工作目录的 .env          —— Tauri 拉起时 cwd 是自己指定的数据目录
      ③ %APPDATA%\\furina-agent\\.env —— 用户配置目录（文档里推荐的位置）
    """
    candidates: list[Path] = []

    if getattr(sys, "frozen", False):
        candidates.append(Path(sys.executable).resolve().parent / ".env")
        candidates.append(Path.cwd() / ".env")
        appdata = os.getenv("APPDATA")
        if appdata:
            candidates.append(Path(appdata) / "furina-agent" / ".env")
    else:
        here = Path(__file__).resolve()
        for parent in list(here.parents)[:5]:
            candidates.append(parent / ".env")

    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


# 模块级加载一次；找不到就交给真实环境变量（容器部署常见）
load_dotenv(dotenv_path=_find_dotenv(), override=False)


class CommonSettings:
    """web 与 desktop 都需要的配置。

    子类各自补自己的字段：
        class WebSettings(CommonSettings): pg_url / redis_url / jwt_*
        class DesktopSettings(CommonSettings): checkpoint_db_path / vector_dir
    """

    def __init__(self) -> None:
        # ---- LLM（两边都要：web 的闲聊、desktop 的 agent 都调同一个模型）----
        self.base_url: str = os.getenv("LLM_BASE_URL", "https://api.deepseek.com/v1")
        self.api_key: str | None = os.getenv("DEEPSEEK_API_KEY")
        self.model: str = os.getenv("LLM_MODEL", "deepseek-v4-flash")

        # ---- 可选：联网搜索（只有 agent 的搜索工具用）----
        self.search_api_key: str | None = os.getenv("BOCHA_SEARCH_API_KEY")

        # ---- agent 文件工具的沙箱根 ----
        # ⚠️ 待办：这里的 "." 兜底在安全上太宽松（沙箱根 = 进程 CWD）。
        #    DesktopSettings 必须显式给一个专用目录。
        self.sandbox_root: Path = Path(os.getenv("SANDBOX_ROOT") or ".")

        # ---- 审批超时扫描（T21）----
        # <- AI 新增：后台扫描的间隔与批量。0 表示关闭后台扫描。
        #    非法值（负数/非正批量）由桌面端启动时 clamp + ERROR 日志处理。
        self.approval_scan_interval_seconds: int = int(
            os.getenv("APPROVAL_SCAN_INTERVAL_SECONDS", "30")
        )
        self.approval_scan_batch_size: int = int(
            os.getenv("APPROVAL_SCAN_BATCH_SIZE", "50")
        )

        # ---- 审批有效期（T23）----
        # 审批创建时写入 deadline_at；超时扫描据此把 Task/Execution 置 SUSPENDED。
        # 迟到决定仍允许恢复（T22 C10），deadline 不是拒绝条件。
        self.approval_timeout_seconds: int = int(
            os.getenv("APPROVAL_TIMEOUT_SECONDS", "3600")
        )

        # ---- 日志 ----
        self.log_level: str = os.getenv("LOG_LEVEL", "INFO")
        # 相对路径按"工作目录"解析，别写进源码树
        # （原 main.py 把 furina.log 落在 CWD，会污染仓库）
        self.log_dir: Path = Path(os.getenv("LOG_DIR", "logs"))

    # ------------------------------------------------------------------
    # 显式校验：谁用谁调用，不在 import 期 raise
    # ------------------------------------------------------------------
    def require_api_key(self) -> str:
        """需要调用 LLM 时调用。缺失给可操作的错误，而不是 None 引发的下游 TypeError。"""
        if not self.api_key:
            raise RuntimeError(
                "缺少大模型密钥（DEEPSEEK_API_KEY）。请在设置页填写，"
                "或设置 LLM_BASE_URL 指向本地的 OpenAI 兼容服务。"
            )
        return self.api_key

    def require_search_key(self) -> str:
        """只有真要联网搜索时才调用。"""
        if not self.search_api_key:
            raise RuntimeError("缺少 BOCHA_SEARCH_API_KEY（联网搜索工具需要）。")
        return self.search_api_key

    def __repr__(self) -> str:
        # 刻意不回显 api_key，避免日志泄漏（防呆清单第 4 条）
        return (
            f"{type(self).__name__}(model={self.model!r}, base_url={self.base_url!r}, "
            f"api_key={'已配置' if self.api_key else '缺失'})"
        )


# 全局单例。两边 import 同一个对象。
# ⚠️ 注意：它**不含** web 的 pg_url/redis_url —— 那些在 furina_web.config.settings。
settings = CommonSettings()


# ----------------------------------------------------------------------
# LLM 客户端：共享一个（两边都调同一个 OpenAI 兼容的服务）
# ----------------------------------------------------------------------
def make_async_client():
    """按 settings 造一个 `openai.AsyncOpenAI` 客户端。

    ⚠️ 这里是**函数**而不是模块级单例，理由：
        · `AsyncOpenAI` 绑定事件循环，模块级创建会在"导入时还没有循环"的场景出问题
        · 密钥可能被用户在**运行中**改（设置页），单例会永远用旧 key

    用法：

        client = make_async_client()
        stream = await client.chat.completions.create(..., stream=True)

    ⚠️ 调用方负责在用完后 `await client.close()`，否则连接泄漏
        （原实现在 `services/stream.py` 里就没关 —— 那是既有问题，搬运时保留了）。
    """
    from openai import AsyncOpenAI  # 延迟导入：不用 LLM 的场景不必加载

    return AsyncOpenAI(
        api_key=settings.api_key or "sk-not-configured",  # 占位，真正调用时才报错
        base_url=settings.base_url,
    )


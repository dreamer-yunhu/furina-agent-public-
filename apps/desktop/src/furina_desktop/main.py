"""桌面版入口 —— 组装 lifespan、挂路由、启动本地服务。

═══════════════════════════════════════════════════════════════════════
它和 web 入口的三个根本差异
═══════════════════════════════════════════════════════════════════════

| | web | desktop |
|---|---|---|
| 存储 | PostgreSQL + Redis | **SQLite（checkpoint）+ LanceDB（待接）** |
| 认证 | 多用户 JWT + 黑名单 + 顶号 | **单用户，无认证**（见 `furina_desktop.auth`） |
| 监听 | 取决于部署（公网） | **只监听 127.0.0.1**（本机） |
| 单实例 | 不需要 | **必须**（见下面第三节） |

**没有"启动失败要回滚"的复杂逻辑**：desktop 只有一个存储依赖（SQLite 文件），
开不了就是开不了 —— 不像 web 那样有三个依赖要逆序回滚。

═══════════════════════════════════════════════════════════════════════
⭐ 为什么必须有单实例锁（两个真实问题）
═══════════════════════════════════════════════════════════════════════

**问题 1：限流器会被绕过。**
    `LocalTokenBucket` 的状态在**进程内存**里。用户双击两次图标 → 两个进程
    → **两个独立的桶** → 实际速率翻倍。加了限流等于没加。

**问题 2：用户会开两个窗口而不自知。**
    Tauri 应用很容易出现"以为关掉了、其实进程还在"。
    然后他在两个窗口里各问一遍，看到两份回答。

**做法**：启动时抢一个文件锁（Windows 上是 `msvcrt.locking`，
POSIX 上是 `fcntl.flock`）。抢不到说明已有实例在跑 → 退出，
并**告诉已有实例把窗口拿到前台**（那部分需要 Tauri 侧配合，见 TODO）。

⚠️ 已知限制：进程被强杀时锁文件会留下。但**文件锁由操作系统释放**，
   所以残留的只是文件本身，不影响下次抢锁 —— 不需要"清理陈旧锁"的逻辑。

═══════════════════════════════════════════════════════════════════════
⚠️ 这一版还缺什么（M0 的活）
═══════════════════════════════════════════════════════════════════════

    · **首次运行配置页**：提示获取大模型密钥（base_url / api_key / model）
    · **密钥校验**：保存前发一次最小请求，把"密钥错"提前到保存那一刻
    · **能力探测**：顺手发一个带 `tools` 的请求，判断该服务商支不支持工具调用
    · **只监听回环的保障**：现在靠 `host="127.0.0.1"` 的默认值，
      应该再加一层断言（防止有人改环境变量把它暴露到局域网）
"""

# ── AI-ASSISTED ── 本文件由 AI 生成/改写，待人工复核 ──
# 复核重点：
#   1. ★ 单实例锁（`SingleInstanceLock`）是**我加的**，旧实现没有。
#      理由见模块 docstring 第三节。**它用了平台相关的 API（msvcrt/fcntl）**，
#      请在你机器上实测：开两个进程，第二个应该退出并打印提示。
#   2. `data/checkpoints.sqlite` 落在**当前工作目录**下 —— 这只是过渡。
#      发布版应该落 `%APPDATA%\furina-agent\`。见 storage/lifespan.py 的 default_db_path。
#   3. 端口 8001（web 用 8000），避免开发时同时跑两个撞车。
#   4. **agent 路由现在跑不通**：`agent_stream` 里还是 `raise NotImplementedError`。
#      本入口的目标是"能起来、能看到 404/500 之外的东西"，不是"功能完整"。

from __future__ import annotations

import logging
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from furina_core.config import settings
from furina_desktop.agent.runtime import AgentRuntime, set_runtime
from furina_desktop.agent.tools.path_jail import ensure_sandbox_root
from furina_desktop.api import agent
from furina_desktop.storage.lifespan import (
    close_checkpoint_store,
    init_checkpoint_store,
)
from furina_desktop.storage.database import close_db, init_db
from furina_desktop.services.timeout_scanner import (
    start_timeout_scanner,
    stop_timeout_scanner,
)

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════
# 单实例锁
# ══════════════════════════════════════════════════════════════════════
class SingleInstanceLock:
    """跨平台的文件锁，保证同一时间只有一个实例在跑。

    用法：

        lock = SingleInstanceLock(path)
        if not lock.acquire():
            print("已有实例在运行")
            sys.exit(0)
        ...
        lock.release()          # 正常退出时调

    为什么不用"检查进程是否存活"：那样有竞态（两个进程同时检查、同时通过）。
    **文件锁是原子的**，由操作系统保证。
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._handle = None

    def acquire(self) -> bool:
        """尝试抢锁。True = 拿到了；False = 已有实例。"""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        # 用 "a+" 而不是 "w"：不要截断别人的锁文件（虽然内容无所谓，
        # 但截断动作本身在 Windows 上会与持锁进程冲突）
        self._handle = open(self._path, "a+")

        try:
            if sys.platform == "win32":
                import msvcrt

                # LK_NBLCK = 非阻塞排他锁。拿不到立刻抛 OSError。
                msvcrt.locking(self._handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self._handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self._handle.close()
            self._handle = None
            return False
        return True

    def release(self) -> None:
        """释放锁。进程退出时操作系统也会释放，但显式释放更干净。"""
        if self._handle is None:
            return
        try:
            if sys.platform == "win32":
                import msvcrt

                self._handle.seek(0)
                msvcrt.locking(self._handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
        except OSError:
            logger.warning("释放单实例锁失败（不影响退出）", exc_info=True)
        finally:
            self._handle.close()
            self._handle = None


def _lock_path() -> Path:
    """锁文件位置。放在数据目录旁边，便于排查。"""
    return Path(os.getenv("FURINA_DATA_DIR", "data")) / "furina.lock"


# ══════════════════════════════════════════════════════════════════════
# 日志
# ══════════════════════════════════════════════════════════════════════
def _setup_logging() -> None:
    """配置日志。**只在 run() 里调用**，不在 import 期。

    ⚠️ 与 web 入口同一处理由：不在 import 期写文件（旧实现踩过这个坑）。
    """
    settings.log_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        filename=str(settings.log_dir / "desktop.log"),
        filemode="a",
        encoding="utf-8",
    )
    # ⚠️ 这两行是**防密钥泄漏**的关键：
    #    httpx / openai 在 DEBUG 下会打印请求头，而请求头里有
    #    `Authorization: Bearer sk-...`。桌面版的日志就落在用户硬盘上。
    for noisy in ("httpx", "httpcore", "openai", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


# ══════════════════════════════════════════════════════════════════════
# lifespan
# ══════════════════════════════════════════════════════════════════════
@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期。

    ⚠️ **顺序有讲究**：先有 checkpoint store，才能装图 ——
       因为 `build_graph` 需要它当 checkpointer。
    """
    logger.info("桌面版启动中")

    # ⓪ 沙箱根（问题 1）
    # <- AI 改动：`.env` 指向的 SANDBOX_ROOT 可能不存在（全新环境就是），
    #    不建的话第一次写入必然 Errno 2，而审批预览已经正常生成了。
    #    复核重点：这里失败要拒绝启动 —— 没有沙箱的文件工具不应该上线。
    try:
        root = ensure_sandbox_root()
        logger.info("沙箱根就绪：%s", root)
    except OSError as exc:
        logger.critical("沙箱根创建失败，拒绝启动：%s", exc)
        raise

    # ① 业务库（user / thread / task / execution / approval）
    # <- AI 改动：新增这一步。原来 desktop 从未设置 app.state.async_session，
    #    导致 get_session 在第一个请求就 AttributeError（阶段 1 报告 B8）。
    try:
        await init_db(app)
    except Exception as exc:
        logger.critical("业务数据库初始化失败，拒绝启动：%s", exc)
        raise

    # ①.5 运行时适配层（T23）：审批落库与执行生命周期。
    # 放在业务库之后、图之前：节点执行时通过 provider 取它。
    app.state.agent_runtime = AgentRuntime(
        app.state.async_session,
        workspace_root=settings.sandbox_root,
        approval_timeout_seconds=settings.approval_timeout_seconds,
    )
    set_runtime(app.state.agent_runtime)
    logger.info(
        "运行时适配层就绪：approval_timeout=%ss",
        app.state.agent_runtime.approval_timeout_seconds,
    )

    # ② checkpoint 存储
    try:
        await init_checkpoint_store(app)
    except Exception as exc:
        logger.critical("SQLite checkpoint 初始化失败，拒绝启动：%s", exc)
        await close_db(app)  # 回滚①
        raise

    # ③ 组装主管图。⚠️ 这是**编排层**的活，放在入口而不是存储层 ——
    # 见 storage/lifespan.py 的模块 docstring（那里解释过为什么拆开）。
    try:
        from furina_desktop.agent.build import build_graph

        app.state.graph = build_graph(app.state.checkpoint_store)
        logger.info("主管图已编译，checkpointer = SQLite")
    except Exception as exc:
        # 图装不起来也要回滚存储，否则 SQLite 文件句柄会留着
        logger.critical("主管图装配失败，拒绝启动：%s", exc)
        await close_checkpoint_store(app)
        await close_db(app)
        raise

    # ④ 审批超时扫描（T21）。⚠️ 它是项目里第一个常驻协程：
    #    启动失败不应拖垮应用，配置非法只降级 + ERROR 日志。
    # <- AI 改动：放在图组装之后、yield 之前；关闭时必须先停它再关存储，
    #    否则扫描器可能拿着已关闭的 session factory 再扫一轮。
    app.state.timeout_scanner_status = start_timeout_scanner(
        app,
        session_factory=app.state.async_session,
        interval=settings.approval_scan_interval_seconds,
        batch=settings.approval_scan_batch_size,
    )
    logger.info("审批超时扫描：%s", app.state.timeout_scanner_status)

    logger.info("就绪，开始接收请求")
    yield

    logger.info("关闭中…")
    # 关闭顺序与初始化相反：先停后台任务，再关存储
    await stop_timeout_scanner(app)
    await close_checkpoint_store(app)
    set_runtime(None)
    app.state.agent_runtime = None
    await close_db(app)
    logger.info("已安全关闭")


# ══════════════════════════════════════════════════════════════════════
# app 工厂
# ══════════════════════════════════════════════════════════════════════
def create_app() -> FastAPI:
    """造 app 实例。用工厂是为了测试能造隔离实例（见 web 入口同处说明）。"""
    app = FastAPI(title="芙宁娜 · 桌面版", lifespan=lifespan)

    # ⚠️ 桌面版的前端是 Tauri（WebView），它的 origin 比较特殊
    #    （Windows 上是 `http://tauri.localhost`）。
    #    开发时前端可能是 localhost:1420（Tauri 默认 devUrl）。
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://tauri.localhost",
            "https://tauri.localhost",
            "http://localhost:1420",
            "http://127.0.0.1:1420",
        ],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(agent.router)

    @app.get("/")
    async def root() -> dict[str, str]:
        """冒烟端点。"""
        return {"app": "furina-desktop", "status": "alive"}

    @app.get("/healthz")
    async def healthz() -> dict[str, object]:
        """健康检查。

        desktop 的健康检查比 web **更有意义**：它可以直接报告
        "checkpoint 存储就绪了吗、图编译了吗、密钥配了吗" ——
        因为这些东西都在同一个进程里。
        """
        return {
            "status": "ok",
            "checkpoint_store": getattr(app.state, "checkpoint_store", None) is not None,
            "graph": getattr(app.state, "graph", None) is not None,
            # <- AI 改动（T21）：排查“为什么没挂起”时第一眼能确认是不是配置关了
            "timeout_scanner": getattr(app.state, "timeout_scanner_status", "unknown"),
            # 只报"配没配"，**绝不回显密钥内容**
            "llm_key_configured": bool(settings.api_key),
        }

    return app


app = create_app()


def run() -> None:
    """启动服务（脚本入口）。

    用法：

        uv run --package furina-desktop furina-desktop
    """
    import uvicorn

    _setup_logging()

    lock = SingleInstanceLock(_lock_path())
    if not lock.acquire():
        logger.error("已有实例在运行，本次启动退出")
        print("芙宁娜已在运行中（检测到单实例锁）。", file=sys.stderr)
        # TODO: 通知已有实例把窗口拿到前台 —— 需要 Tauri 侧提供一个 IPC 端点
        sys.exit(0)

    try:
        # ⚠️ 只监听回环地址。桌面版的服务**不应该**被局域网访问。
        host = os.getenv("DESKTOP_HOST", "127.0.0.1")
        if host not in ("127.0.0.1", "localhost", "::1"):
            # 这是一个"防呆"：如果有人在环境变量里把它改成 0.0.0.0，
            # 那这台机器上的一切都暴露给同网段了。宁可拒绝启动。
            raise RuntimeError(
                f"DESKTOP_HOST 只能绑回环地址（当前 {host!r}）—— "
                "桌面版本地服务不允许暴露到局域网。"
            )
        port = int(os.getenv("DESKTOP_PORT", "8001"))
        logger.info("启动 uvicorn: http://%s:%d", host, port)
        uvicorn.run("furina_desktop.main:app", host=host, port=port, reload=False)
    finally:
        lock.release()


if __name__ == "__main__":
    run()

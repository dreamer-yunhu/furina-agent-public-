"""web 版入口 —— 组装 lifespan、挂路由、启动服务。

═══════════════════════════════════════════════════════════════════════
本文件修掉的旧实现的三个问题（都有实测依据）
═══════════════════════════════════════════════════════════════════════

**① import 期写日志文件**（原 `main.py` 第 44-51 行）
    原实现把 `logging.basicConfig(filename="furina.log")` 放在**模块底部**：
        · 模块底部 = **import 时就执行**，而不是启动时
        · 后果：`import app.main` 会往进程 CWD 写文件 ——
          我实测过它因此失败（`PermissionError: ... furina.log`），
          而且这也污染了源码目录
    现在：日志初始化抽成 `_setup_logging()`，**只在 `run()` 里调用**。

**② 日志级别全局 DEBUG**
    会打印 SQL 与 HTTP 请求详情，**包括 `Authorization` 头**
    —— 桌面版是本地应用、web 版日志也会落盘，等于把 API key 写进日志。
    现在：默认 INFO，第三方库一律 WARNING（见 `_setup_logging`）。

**③ CORS 无条件 `allow_origins=["*"]`**
    原注释写着"演示环境全放开"。现在改成：**默认只允许本机**，
    需要放开时用环境变量显式声明（见 `_cors_origins`）。

═══════════════════════════════════════════════════════════════════════
启动顺序与回滚（沿用旧实现的思路，这里写得更明确）
═══════════════════════════════════════════════════════════════════════

    init_db → init_redis → create_table
    任一步失败 → **逆序回滚已初始化的部分** → 抛出（拒绝启动）

    关闭时逆序：create_table 无需关闭 → close_redis → close_db

**这个"失败要回滚"的设计是旧实现就有的，我保留了** ——
因为半启动状态（PG 连上了、Redis 没连上）比直接不启动更难排查。
"""

# ── AI-ASSISTED ── 本文件由 AI 生成/改写，待人工复核 ──
# 复核重点：
#   1. ★ 日志初始化从"import 时"改到了"run() 时"。这是**行为变更**：
#      以前 `import furina_web.main` 就会配好日志，现在不会。
#      如果你依赖"import 后就配好日志"（比如 uvicorn --reload 直接指向 app），
#      告诉我改回去 —— 但要接受 import 期写文件。
#   2. CORS 默认收紧为"只允许本机"。你可能想要 `*`（开发方便）——
#      用 `CORS_ORIGINS=*` 环境变量即可，见 _cors_origins()。
#   3. 端口的默认值我用了 8000（与旧实现一致）。桌面版用 8001，避免撞车。

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse

from furina_web.config import settings
from furina_web.routers import asset, auth, chat, knowledge, user, ws
from furina_web.storage.database import close_db, create_table, init_db
from furina_web.storage.redis_client import close_redis, init_redis

logger = logging.getLogger(__name__)


def _setup_logging() -> None:
    """配置日志。**只在 run() 里调用**，不在 import 期。

    为什么这样做：见模块 docstring 第 ① 条。
    """
    settings.log_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        filename=str(settings.log_dir / "web.log"),
        filemode="a",
        encoding="utf-8",
    )
    # ⚠️ 关键：把爱说话的第三方库压到 WARNING。
    #    httpx / openai / sqlalchemy 在 DEBUG 下会打印请求头（含 Authorization）。
    for noisy in ("httpx", "httpcore", "openai", "sqlalchemy.engine", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：顺序初始化，失败逆序回滚。"""
    logger.info("web 版启动中")

    # ---- ① PostgreSQL ----
    try:
        await init_db(app)
    except Exception as exc:
        logger.critical("PostgreSQL 初始化失败，拒绝启动：%s", exc)
        raise

    # ---- ② Redis（失败要回滚 PG）----
    try:
        await init_redis(app)
    except Exception as exc:
        logger.critical("Redis 初始化失败，拒绝启动：%s", exc)
        await close_db(app)  # ← 回滚①
        raise

    # ---- ③ 建表（失败要回滚① ②）----
    try:
        await create_table(app)
    except Exception as exc:
        logger.critical("建表失败，拒绝启动：%s", exc)
        await close_redis(app)  # ← 回滚②
        await close_db(app)  # ← 回滚①
        raise

    logger.info("所有依赖就绪，开始接收请求")
    yield

    # ---- 关闭：逆序 ----
    logger.info("web 版关闭中…")
    await close_redis(app)
    await close_db(app)
    logger.info("已安全关闭")


def _cors_origins() -> list[str]:
    """CORS 白名单。

    默认**只允许本机**（开发时的前端 dev server）。
    要开放时设 `CORS_ORIGINS=https://your.domain,https://another`
    或 `CORS_ORIGINS=*`（**仅开发用**，公网部署别这么干）。
    """
    raw = os.getenv("CORS_ORIGINS", "").strip()
    if not raw:
        return ["http://localhost:5173", "http://127.0.0.1:5173"]
    if raw == "*":
        return ["*"]
    return [o.strip() for o in raw.split(",") if o.strip()]


def create_app() -> FastAPI:
    """工厂函数：造 app 实例。

    用工厂而不是模块级 `app = FastAPI(...)` 的好处：**测试时可以造多个隔离实例**，
    而模块级单例会让测试之间互相污染（app.state 是共享的）。
    """
    app = FastAPI(title="芙宁娜 · Web 版", lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins(),
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 业务路由。注意**顺序无关**，但不能漏 —— 漏一个就是 404。
    app.include_router(auth.router)  # 认证
    app.include_router(user.router)  # 用户
    app.include_router(chat.router)  # 对话（闲聊）
    # ⚠️ AI 改动：**不再 include agent.router**。
    #    `/agent/*`（线程 CRUD + 流式对话）已归桌面版
    #    （`furina_desktop.api.agent`）—— 它是 agent 编排的接口，
    #    依赖 LangGraph 图与 checkpointer，而 web 版没有这些。
    #    原来在旧 main.py 里挂载它，是因为那时两个产品共用一个 app。
    app.include_router(knowledge.router)  # 知识库（预留，零端点）
    app.include_router(asset.router)  # 资源（预留，零端点）
    app.include_router(ws.router)  # WebSocket 回声（预留）

    @app.get("/")
    async def root() -> dict[str, str]:
        """冒烟端点：确认服务活着。"""
        return {"Hello": "World"}

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        """健康检查：给容器编排 / 反向代理用。

        ⚠️ 现在只回 "ok"，**没有真的探 PG / Redis**。
           真正的健康检查应该试试 `SELECT 1` 和 `PING` —— 留到 M0 之后。
        """
        return {"status": "ok"}

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        """兜底异常处理：记全 traceback，对外只说"服务器开小差了"。

        ⚠️ 注意：**不要让异常泄漏到客户端** —— 堆栈里可能有 SQL、路径、甚至密钥。
        """
        logger.error("未处理异常", exc_info=exc)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": "服务器开小差了"},
        )

    return app


app = create_app()


def run() -> None:
    """启动服务（脚本入口）。

    用法：

        uv run --package furina-web furina-web
        # 或
        python -m furina_web.main
    """
    import uvicorn

    _setup_logging()  # ★ 在这里配日志，不在 import 期（见模块 docstring ①）
    host = os.getenv("WEB_HOST", "127.0.0.1")
    port = int(os.getenv("WEB_PORT", "8000"))
    logger.info("启动 uvicorn: http://%s:%d", host, port)
    uvicorn.run("furina_web.main:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    run()

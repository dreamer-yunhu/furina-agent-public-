"""通用存储辅助 —— 只放"两边都可能要"的东西。

    session.py   FastAPI 的会话依赖（get_session）

⚠️ **这里没有 PG 引擎、没有 Redis、没有建表逻辑** —— 那些都是 web 专属，
   在 `furina_web.storage`。core 的红线是"**零存储后端**"：
   不 import asyncpg / psycopg / redis / lancedb。

   （`sqlmodel` / `sqlalchemy` 是允许的：`furina_core.models` 用它定义**共享的表结构**，
     `sqlalchemy.ext.asyncio.AsyncSession` 只是**类型**，两者都不引入具体后端驱动。
     这条边界上一轮被写成过"不 import sqlmodel"，实测不成立，已更正。）
"""

# ── AI-ASSISTED ── 本文件由 AI 生成/改写，待人工复核 ──
# 复核重点：纯导出。desktop 用 SQLite 时该往这里加什么，见 session.py 的说明。

from furina_core.storage.session import get_session

__all__ = ["get_session"]

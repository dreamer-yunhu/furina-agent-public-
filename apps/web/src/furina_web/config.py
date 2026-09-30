"""web 版的配置 —— 继承 core 的公共配置，补上 PG / Redis / JWT。

═══════════════════════════════════════════════════════════════════════
为什么这些字段不在 core（一个刻意的划分）
═══════════════════════════════════════════════════════════════════════

实测字段分布：
    base_url / api_key / search_api_key / sandbox_root  → 两边都要  → core
    pg_url / redis_url / jwt_*                          → **只有 web** → 本文件

**桌面版不装 PG、不装 Redis**（这是"开箱即用"的定义），
所以把这些字段放 core，等于让 desktop 白读一堆它永远用不到的配置
—— 那正是重构要消除的"共享层变垃圾桶"。
"""

# ── AI-ASSISTED ── 本文件由 AI 生成/改写，待人工复核 ──
# 复核重点：
#   1. 本文件是**新建**的 —— 原来的 `WebSettings` 在 core 的 config.py 里，
#      我把它搬出来了。core 现在只剩 `CommonSettings` + 全局 `settings`。
#   2. ★ 新增了 `require_pg_url()` / `require_redis_url()`：PG 和 Redis 是
#      web **启动必须**的（不像 LLM key 可以等到第一次调用才检查），
#      所以启动时校验。
#   3. `jwt_key` 原本是从 `JWT_SECRET_KEY` 环境变量读。注意 `security.py` 的
#      兼容垫片也读同一个变量 —— 两处读同一份配置，是有意为之（垫片拿不到本对象）。

from __future__ import annotations

import os

from furina_core.config import CommonSettings


class WebSettings(CommonSettings):
    """web 版：多用户 + PostgreSQL + Redis。"""

    def __init__(self) -> None:
        super().__init__()
        # ---- 存储：PostgreSQL（业务表）----
        self.pg_url: str | None = os.getenv("PG_URL")

        # ---- 缓存 / 会话：Redis ----
        self.redis_url: str | None = os.getenv("REDIS_URL")

        # ---- 认证：JWT ----
        self.jwt_key: str | None = os.getenv("JWT_SECRET_KEY")
        self.jwt_algo: str = os.getenv("JWT_ALGO", "HS256")
        self.access_token_expire_seconds: int = int(
            os.getenv("ACCESS_TOKEN_EXPIRE_SECONDS", "3600")
        )
        self.refresh_token_expire_days: int = int(
            os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "30")
        )

    # ------------------------------------------------------------------
    # 启动期校验（这两个是硬依赖，不像 LLM key 可以延后）
    # ------------------------------------------------------------------
    def require_pg_url(self) -> str:
        """PostgreSQL 连接串。**启动时必须校验** —— 引擎建不起来就没法服务。"""
        if not self.pg_url:
            raise RuntimeError(
                "缺少 PG_URL。web 版需要 PostgreSQL；"
                "本地开发可用 Docker：docker run -e POSTGRES_PASSWORD=... -p 5432:5432 postgres:16"
            )
        return self.pg_url

    def require_redis_url(self) -> str:
        """Redis 连接串。启动时必须校验。"""
        if not self.redis_url:
            raise RuntimeError(
                "缺少 REDIS_URL。web 版用它做热缓存 / JWT 黑名单 / 会话登记。"
            )
        return self.redis_url

    def require_jwt_key(self) -> str:
        """JWT 密钥。

        ⚠️ **不能有默认值**：HS256 用一个写死的默认密钥，等于全世界都能伪造令牌。
        """
        if not self.jwt_key:
            raise RuntimeError(
                "缺少 JWT_SECRET_KEY。web 版签发令牌必须显式配置，不能使用默认值。"
            )
        return self.jwt_key


# 全局单例。**注意它和 `furina_core.config.settings` 是两个对象**：
#   furina_core.config.settings  → CommonSettings（两边都用的那部分）
#   furina_web.config.settings   → WebSettings（本文件，多出 PG/Redis/JWT）
settings = WebSettings()

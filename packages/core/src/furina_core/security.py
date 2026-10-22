"""认证原语：口令哈希 + JWT 签发/校验。

与原始 `app/core/security.py` 的三处关键差异：

1. **不再抛 `HTTPException`** —— core 不认识 HTTP，也就不该 import fastapi。
   改为抛 `TokenError`（携带 `kind` 供调用方映射状态码）。
   - web：`except TokenError as e: raise HTTPException(401, ...)`
   - desktop：单用户，直接当作"本地令牌无效"处理
2. **不在 import 期依赖全局 settings** —— `jwt_key` / `algo` 由调用方传入。
   好处：desktop 可以用自己的本地密钥，不必伪造一个 JWT_SECRET_KEY 环境变量。
3. **`sub` / `id` 命名分裂的问题原样保留但标注** —— 原始代码 access 用 `sub`、
   refresh 用 `id`，同一语义两个键名，靠 `sub == id` 做归属校验（见 docs/NOTES.md）。
   这是既成契约，core 不擅自统一，但下面 `TokenPayload` 里写明了两者的对应关系。
"""

# ── AI-ASSISTED ── 本文件由 AI 生成/改写，待人工复核 ──
# 复核重点（三处按重要度排序）：
#   1. `TokenError` 取代 `HTTPException` 是我的改动。**调用方必须跟着改**：
#      web 侧要把 `except TokenError` 翻成 401/403，否则令牌过期会变成 500。
#   2. `session_id` 从必填改成可选 —— 为了让 desktop 能复用。
#      请确认 web 侧不会因此漏做"顶号"校验（漏了就是会话隔离失效）。
#   3. `verify_password` 我包了 try/except 返回 False。原来会抛异常。
#      好处：脏哈希不会变 500；坏处：**真实的 bug 会被静默吞掉**。

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import bcrypt
import jwt

TokenType = Literal["access", "refresh"]

_BCRYPT_ROUNDS = 12


# ----------------------------------------------------------------------
# 异常：core 自己的类型，不依赖任何 Web 框架
# ----------------------------------------------------------------------
class TokenError(Exception):
    """令牌不可用。`kind` 供调用方决定状态码。"""

    def __init__(self, kind: Literal["expired", "invalid"], detail: str) -> None:
        self.kind = kind
        self.detail = detail
        super().__init__(detail)


# ----------------------------------------------------------------------
# 口令
# ----------------------------------------------------------------------
def hash_password(password: str) -> str:
    """bcrypt 哈希（rounds=12）。返回 str，便于直接入库。"""
    return bcrypt.hashpw(
        password.encode("utf-8"),
        bcrypt.gensalt(rounds=_BCRYPT_ROUNDS),
    ).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """校验口令。哈希格式非法时返回 False，不抛异常（避免把 422 变成 500）。"""
    try:
        return bcrypt.checkpw(
            plain_password.encode("utf-8"),
            hashed_password.encode("utf-8"),
        )
    except (ValueError, TypeError):
        return False


# ----------------------------------------------------------------------
# JWT
# ----------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class TokenPayload:
    """解码后的载荷。

    `subject` 统一了原始代码里 access 用 `sub` / refresh 用 `id` 的分裂：
    构造时两者都填，读取时优先 `sub`。
    """

    subject: str
    token_type: str
    jti: str
    session_id: str | None
    expires_at: int
    raw: dict[str, Any]

    @property
    def remaining_seconds(self) -> int:
        """剩余有效期（不小于 0）——拉黑令牌时的 TTL 就用它。"""
        return max(0, self.expires_at - int(datetime.now(UTC).timestamp()))


def create_token(
    *,
    subject: uuid.UUID | str,
    token_type: TokenType,
    jwt_key: str,
    algorithm: str = "HS256",
    expires_delta: timedelta,
    session_id: uuid.UUID | str | None = None,
    extra_claims: dict[str, Any] | None = None,
) -> str:
    """签发令牌。

    `session_id` 是可选的：web 用它做"单会话/顶号"，desktop 单用户不需要，传 None 即可。
    这一点是 core 能被两边共用的关键 —— 原始 `create_jwt` 把 session_id 写成了必填。
    """
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": str(subject),
        "id": str(subject),  # 兼容原始的 refresh 令牌契约（读 `id`）
        "type": token_type,
        "jti": str(uuid.uuid4()),
        "iat": now,
        "exp": now + expires_delta,
    }
    if session_id is not None:
        payload["session_id"] = str(session_id)
    if extra_claims:
        payload.update(extra_claims)

    return jwt.encode(payload, jwt_key, algorithm=algorithm)


def decode_token(token: str, *, jwt_key: str, algorithm: str = "HS256") -> TokenPayload:
    """校验并解码令牌。失败抛 `TokenError`，不抛 HTTPException。"""
    try:
        data: dict[str, Any] = jwt.decode(token, jwt_key, algorithms=[algorithm])
    except jwt.ExpiredSignatureError as exc:
        raise TokenError("expired", "令牌已过期") from exc
    except jwt.InvalidTokenError as exc:
        raise TokenError("invalid", "无效令牌") from exc

    subject = data.get("sub") or data.get("id")
    if not subject:
        raise TokenError("invalid", "令牌缺少主体标识")

    return TokenPayload(
        subject=str(subject),
        token_type=str(data.get("type", "")),
        jti=str(data.get("jti", "")),
        session_id=data.get("session_id"),
        expires_at=int(data.get("exp", 0)),
        raw=data,
    )


def require_token_type(payload: TokenPayload, expected: TokenType) -> None:
    """强制令牌类型。原始实现用它拒绝"拿 refresh 当 access 用"。"""
    if payload.token_type != expected:
        raise TokenError("invalid", f"需要 {expected} 令牌")


# ══════════════════════════════════════════════════════════════════════
# 向后兼容层 —— 让既有调用点不用改
# ══════════════════════════════════════════════════════════════════════
# ⚠️ 这三个函数是**兼容垫片**，不是设计目标。
#
# 背景：我在写 core 时把原来的 `create_jwt` / `create_access_token` /
# `create_refresh_token` 合并成了一个 `create_token(*, subject, token_type, jwt_key, ...)`，
# 理由是让 `session_id` 变成可选（desktop 单用户不需要）。
# 但 web 侧有 7 处调用点仍用旧签名，4 处 `decode_token` 不传 jwt_key。
#
# **两条路**：A（本文件所做）补垫片；B 改 web 侧的 7+4 处调用。
# 选了 A，因为：改动小、web 代码零修改、且**旧签名本身是合理的外部契约**。
#
# ⚠️ 密钥来源是这里唯一"不干净"的地方：从环境变量读，而不是从传入的 settings。
#    理由：core 不 import 具体 app（红线二）。等 `furina_web.config` 建好后，
#    更干净的做法是 web 侧显式传 key —— 那时这三个垫片可以删掉。
#
# ── AI 改动（本轮复核结论）── 复核重点，别跳过：
#    2026 本轮把 web 侧 20 处调用点全部按 `TokenPayload` 属性访问改写完毕
#    （auth/dependencies.py、services/user.py），**调用点已经不再依赖"垫片"这层兼容**，
#    真正的迁移（web 显式传 key、删掉这三个函数）现在是可行的，但**我没有擅自删**：
#      · 它是公开 API 的一部分（`from furina_core.security import create_access_token`
#        是 web 现在正在用的写法），删掉要同时新增一个 web 侧 token 适配模块；
#      · 这是设计决定，不是 bug 修复（AGENTS.md §二.3：只做有调用者的修改）。
#    黑盒使用者请优先用 `create_token` / `decode_token`（密钥显式传）；
#    这三个函数的契约、参数、TTL 常量写进了 packages/core/README.md。
#    实测：密钥缺失时它们抛 `RuntimeError`（不是 TokenError），见 `_env_jwt_key`。

_DEFAULT_ALGO = "HS256"
_ACCESS_TTL_SECONDS = 3600
_REFRESH_TTL_DAYS = 30


def _env_jwt_key() -> str:
    """取 JWT 密钥。

    ⚠️ **缺失就报错，不给默认值** —— HS256 用一个写死的默认密钥，
       等于全世界都能伪造你的令牌。这是"fail-closed"而不是"能用就行"。

    ── AI 改动 ── 复核重点：这里原来抛的是 `TokenError("invalid", ...)`，语义不对 ——
       **"密钥没配"是配置错误，不是"令牌不可用"**。而调用方的标准做法是把 `TokenError`
       翻成 401，那会把一次部署事故伪装成"用户令牌无效"，排障时极难定位。
       现改为 `RuntimeError`（和 `CommonSettings.require_api_key()` 同一类错误），
       让它老老实实变成 500。**如果你更希望它保持 TokenError，告诉我改回去。**
    """
    import os

    key = os.getenv("JWT_SECRET_KEY")
    if not key:
        raise RuntimeError(  # <- AI 改动（原 TokenError("invalid", ...)）
            "缺少 JWT_SECRET_KEY —— 签发/校验令牌必须显式配置密钥，不能使用默认值。"
        )
    return key


def _env_jwt_algo() -> str:
    import os

    return os.getenv("JWT_ALGO") or _DEFAULT_ALGO


def create_access_token(user_id: Any, user_name: str, session_id: Any) -> str:
    """签发访问令牌（兼容旧签名：位置或关键字传参都能用）。

    ⚠️ 注意 `user_name` 目前**不写进载荷** —— 原始实现把它放进 `name` 字段，
       但没有任何地方读它（用户名应该查库拿，不该信令牌里的旧值）。
       如果你要保留，告诉我加回去。
    """
    del user_name  # 刻意不使用，见 docstring
    return create_token(
        subject=user_id,
        token_type="access",
        jwt_key=_env_jwt_key(),
        algorithm=_env_jwt_algo(),
        expires_delta=timedelta(seconds=_ACCESS_TTL_SECONDS),
        session_id=session_id,
    )


def create_refresh_token(user_id: Any, user_name: str, session_id: Any) -> str:
    """签发刷新令牌（兼容旧签名）。"""
    del user_name
    return create_token(
        subject=user_id,
        token_type="refresh",
        jwt_key=_env_jwt_key(),
        algorithm=_env_jwt_algo(),
        expires_delta=timedelta(days=_REFRESH_TTL_DAYS),
        session_id=session_id,
    )


def decode_token_compat(token: str) -> TokenPayload:
    """解码令牌（从环境变量取密钥）。

    这是给"不想每次传 jwt_key"的调用点用的便捷版本。
    **优先用 `decode_token(token, jwt_key=...)`** —— 显式传参更容易测试。
    """
    return decode_token(token, jwt_key=_env_jwt_key(), algorithm=_env_jwt_algo())

"""
写门禁的
"""

# ── AI-ASSISTED ── 本文件由 AI 生成/改写，待人工复核 ──
# 复核重点（本次修复）：core 的 `decode_token` 与"名字兼容"的旧实现**返回类型不同**——
#   老实现返回 dict，core 的 `decode_token_compat` 返回 `TokenPayload`（dataclass）。
#   所以下面这些都必须跟着改，否则每个带鉴权的请求都会 500：
#       payload.get("type")       -> payload.token_type
#       payload.get("jti")        -> payload.jti
#       payload.get("session_id") -> payload.session_id
#       payload.get("sub")        -> payload.subject
#   另外 core 不再抛 HTTPException 而是抛 TokenError —— 不接住的话"令牌过期"会变成 500，
#   正确响应是 401（见下面 try/except TokenError 那一段）。

import uuid
import logging
from redis import asyncio as aioredis, RedisError
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio.session import AsyncSession
from fastapi import HTTPException,status,Depends
from furina_core.storage.session import get_session
from furina_web.storage.redis_client import get_redis, get_redis_fuse
from furina_core.circuit_breaker import CircuitBreaker as RedisFuse, CircuitOpenError
from furina_core.circuit_policies import fail_closed as fuse_fail_closed
from furina_core.security import TokenError, decode_token_compat as decode_token  # <- AI 改动：签收 TokenError
from furina_core.models import User
from furina_web.repositories.redis_user import is_blocklisted, is_current_session
from furina_web.repositories.user import get_user_by_id

#配置日志
logger = logging.getLogger(__name__)

#写“门禁”函数
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

async def get_current_user(
        token: str = Depends(oauth2_scheme),
        session: AsyncSession = Depends(get_session),
        redis : aioredis.Redis = Depends(get_redis),
        fuse : RedisFuse = Depends(get_redis_fuse)
)->User:
    """
    验证令牌 → 提取用户ID → 查数据库 → 返回用户对象
    :param fuse: redis熔断器
    :param redis: redis客户端
    :param token: 令牌
    :param session: 数据库会话对象
    :return: 用户模型
    """

    #解码token
    # ── AI 改动 ── 复核重点：core 的解码器抛 TokenError（不是 HTTPException）。
    #    原代码没有 try，令牌过期/被篡改时这里会冒到 FastAPI 变成 500 —— 正确语义是 401。
    try:
        payload = decode_token(token)
    except TokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="令牌已过期，请重新登录" if exc.kind == "expired" else "无效令牌",
        ) from exc

    # 安全策略：只允许 access token，拒绝 refresh token
    if payload.token_type != "access":  # <- AI 改动（原 payload.get("type")）
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail= "请使用访问令牌"
        )
    #提取jti——令牌全局唯一uuid
    jti = payload.jti                      # <- AI 改动（原 payload.get("jti")）
    session_id = payload.session_id        # <- AI 改动（原 payload.get("session_id")）
    #防御性编程
    if not jti:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,detail="无效访问令牌id")
    #检查是否在redis的黑名单中
    try:
        if await fuse_fail_closed(fuse,is_blocklisted,redis,jti,action="门禁黑名单校验"):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,detail="令牌位于黑名单中")
    except (RedisError, CircuitOpenError):
        logger.error("认证路径：redis不可用——无法确定令牌是否再黑名单中，向客户端返回503")
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="服务暂不可用,请稍后再试")
    #提取用户id
    user_id = payload.subject  # <- AI 改动（原 payload.get("sub")；core 里 sub 与 id 同值）
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="令牌无效"
        )
    #检查会话id是不是当前会话id
    if not session_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,detail="无效会话id")
    try:
        if not await fuse_fail_closed(fuse,is_current_session,redis,session_id,user_id,action="门禁会话对账"):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,detail="会话id不是当前会话id")
    except (RedisError, CircuitOpenError):
        logger.error("认证路径：redis不可用——无法确定令牌里的会话id是否为当前会话id，向客户端返回503")
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="服务暂不可用,请稍后再试")

    #从数据库查出用户对象
    user  = await get_user_by_id(session,uuid.UUID(user_id))
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail = "用户不存在"
        )

    return user


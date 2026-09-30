"""
写门禁的
"""
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
from furina_core.security import decode_token_compat as decode_token
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
    payload = decode_token(token)

    # 安全策略：只允许 access token，拒绝 refresh token
    if payload.get("type") != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail= "请使用访问令牌"
        )
    #提取jti——令牌全局唯一uuid
    jti = payload.get("jti")
    session_id = payload.get("session_id")
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
    user_id = payload.get("sub")
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


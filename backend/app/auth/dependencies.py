"""
写门禁的
"""
import uuid
from redis import asyncio as aioredis
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio.session import AsyncSession
from fastapi import HTTPException,status,Depends
from app.core.database import get_session
from app.core.redis_client import get_redis
from app.core.security import decode_token
from app.models.table import User
from app.repositories.redis_user import is_blocklisted, is_current_session
from app.repositories.user import get_user_by_id

#写“门禁”函数
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

async def get_current_user(
        token: str = Depends(oauth2_scheme),
        session: AsyncSession = Depends(get_session),
        redis : aioredis.Redis = Depends(get_redis)
)->User:
    """
    验证令牌 → 提取用户ID → 查数据库 → 返回用户对象
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
    if await is_blocklisted(redis,jti):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,detail="令牌位于黑名单中")

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

    if not await is_current_session(redis,session_id,user_id):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,detail="会话id不是当前会话id")

    #从数据库查出用户对象
    user  = await get_user_by_id(session,uuid.UUID(user_id))
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail = "用户不存在"
        )

    return user


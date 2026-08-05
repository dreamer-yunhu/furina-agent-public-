"""
写门禁的
"""
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio.session import AsyncSession
from fastapi import HTTPException,status,Depends
from app.core.database import get_session
from app.core.security import decode_token
from app.models.table import User
from app.repositories.crud import get_user_by_id

#写“门禁”函数
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/login")

async def get_current_user(
        token: str = Depends(oauth2_scheme),
        session: AsyncSession = Depends(get_session)
)->User:
    """
    验证令牌 → 提取用户ID → 查数据库 → 返回用户对象
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
    # 从令牌载荷中提取id
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail= "令牌无效"
        )
    #从数据库查出用户对象
    user  = await get_user_by_id(session, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail = "用户不存在"
        )

    return user


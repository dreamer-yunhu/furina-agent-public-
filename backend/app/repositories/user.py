"""
用户表 CRUD：只做持久化，不做业务判断。
会话/消息的 CRUD 已迁移到 repositories/conversation.py 与 repositories/message.py。
"""
import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.security import hash_password
from app.models.table import User
from app.schemas.model import UserCreate, PasswordReset

logger = logging.getLogger(__name__)


async def get_user_by_name(session: AsyncSession, username: str) -> User:
    query = await session.execute(select(User).where(User.user_name == username))
    user = query.scalar_one_or_none()
    logger.debug("用户信息查询功能正常（名称查询）")
    return user


async def get_user_by_id(session: AsyncSession, user_id: uuid.UUID) -> User:
    query = await session.execute(select(User).where(User.id == user_id))
    user = query.scalar_one_or_none()
    logger.debug("用户信息查询功能正常（id查询）")
    return user


async def user_create(session: AsyncSession, inform: UserCreate) -> User:
    new_user = User(
        user_name=inform.username,
        hashed_password=hash_password(inform.password),
        personal_preference=inform.hobby
    )
    try:
        session.add(new_user)
        await session.commit()
        await session.refresh(new_user)
        logger.debug("注册信息录入函数正常")
        return new_user
    except Exception as e:
        logger.exception("注册功能异常", e)
        await session.rollback()


async def reset_pwd(session: AsyncSession, inform: PasswordReset) -> bool:
    query = await session.execute(select(User).where(User.user_name == inform.username))
    db_user = query.scalar_one_or_none()
    if not db_user:
        return False
    db_user.hashed_password = hash_password(inform.new_password)
    await session.commit()
    await session.refresh(db_user)
    return True

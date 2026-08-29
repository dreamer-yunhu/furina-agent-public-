"""
用户表 CRUD：只做持久化，不做业务判断。
会话/消息的 CRUD 已迁移到 repositories/conversation.py 与 repositories/message.py。
"""
import logging
import uuid
from sqlalchemy import select,update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.security import hash_password
from app.models.table import User
from app.schemas.model import UserCreate, PasswordReset

logger = logging.getLogger(__name__)


async def get_user_by_name(session: AsyncSession, username:str) -> User:
    query = await session.execute(select(User).where(User.user_name == username))
    user = query.scalar_one_or_none()
    logger.debug("用户信息查询功能正常（名称查询）")
    return user


async def get_user_by_id(session: AsyncSession, user_id: uuid.UUID) -> User:
    query = await session.execute(select(User).where(User.id == user_id))
    user = query.scalar_one_or_none()
    logger.debug("用户信息查询功能正常（id查询）")
    return user

async def get_other_user_by_name(session: AsyncSession,username:str,exclude_user_id:uuid.UUID) -> User|None:
    query = await session.execute(select(User).where(User.user_name == username,User.id != exclude_user_id))
    other_user = query.scalar_one_or_none()
    return other_user


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
        #1-logger.exception(msg, e) 的 msg 无 %s 却传 e → logging 二次抛错被吞，真异常被掩盖
        #2-except 缺 return → 函数返回 None → auth.py 崩在 None.id，把 400 伪装成 500
        #修复：exc_info=e 传递异常，raise 让异常冒泡，由上层统一处理
        logger.exception("注册功能异常", exc_info=e)
        await session.rollback()
        raise

async def user_reset(session: AsyncSession,user_id,update_dict:dict) ->User:
    stmt = update(User).where(User.id == user_id).values(**update_dict)#**是python的字典解包符号，会把字典拆解为变量名=值的形式
    try:
        await session.execute(stmt) #执行
        await session.commit()
        return await get_user_by_id(session,user_id)
    except IntegrityError:
        await session.rollback()
        raise

    except Exception as e:
        logger.exception("更新用户信息异常", exc_info=e)
        await session.rollback()
        raise

async def reset_pwd(session: AsyncSession, inform: PasswordReset) -> bool:
    query = await session.execute(select(User).where(User.user_name == inform.username))
    db_user = query.scalar_one_or_none()
    if not db_user:
        return False
    db_user.hashed_password = hash_password(inform.new_password)
    await session.commit()
    await session.refresh(db_user)
    return True

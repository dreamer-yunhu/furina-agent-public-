import logging
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.security import hash_password
from app.models.table import User, Conversation, Message
from app.schemas.model import UserCreate, ConservationCreate, PasswordReset, MessageCreate

logger = logging.getLogger(__name__)

#定义查询用户函数
async def get_user_by_name(session: AsyncSession,username:str) -> User:
    query = await session.execute(select(User).where(User.user_name ==username))
    user = query.scalar_one_or_none()
    logger.debug("用户信息查询功能正常（名称查询）")
    return user

async def get_user_by_id(session: AsyncSession,uuid:str) -> User:
    query = await session.execute(select(User).where(User.id == uuid))
    user = query.scalar_one_or_none()
    logger.debug("用户信息查询功能正常（id查询）")
    return user


#定义写入注册信息函数
async def user_create(session:AsyncSession,inform:UserCreate):
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
        logger.exception("注册功能异常",e)
        await session.rollback()

#定义找回密码函数
async def reset_pwd(session: AsyncSession,inform:PasswordReset):
    query = await session.execute(select(User).where(User.user_name == inform.username))
    db_user = query.scalar_one_or_none()
    db_user.hashed_password = hash_password(inform.new_password)
    await session.commit()
    await session.refresh(db_user)
    return True





#定义创建会话函数
async def create_conservation(session: AsyncSession,inform:ConservationCreate):
    new_conservation = Conversation(
        title = inform.title,
        user_id = False#占位的
    )
    session.add(new_conservation)
    await session.commit()
    await session.refresh(new_conservation)
    logger.debug("会话创建函数正常")
    return True

#定义用户消息历储存函数
async def save_user_messages_records(session:AsyncSession,inform:MessageCreate):
    new_user_message = Message(
        content = inform.contents,
        conversation_id = 1 #占位的
    )
    session.add(new_user_message)
    await session.commit()
    await session.refresh(new_user_message)
    logger.debug("对话历史正常存储")
    return True

#定义大模型回复消息存储函数
async def save_llm_messages_records(session:AsyncSession,inform:MessageCreate):
    new_llm_message = Message(
        role = inform.role.ASSISTANT,
        content = inform.contents,
        conversation_id = 1 #占位的
    )
    session.add(new_llm_message)
    await session.commit()
    await session.refresh(new_llm_message)
    logger.debug("大模型回复存储正常")
    return True

#定义获取大模型历史回复消息函数
async def get_llm_messages(session:AsyncSession,):
    pass
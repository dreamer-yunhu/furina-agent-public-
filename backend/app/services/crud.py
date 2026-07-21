"""
用于执行CRUD操作
"""
from app.schemas.model import User,Conversation, Message,UserCreate,ConservationCreate,MessageCreate
from sqlmodel import Session, select
import uuid
from typing import Any
import logging
logger = logging.getLogger(__name__)

#将用户信息写入数据库
def create_user(*,session: Session,user_create: UserCreate) -> User:
    logger.debug("开始创建用户信息")
    db_obj =User.model_validate(
        user_create,
        update={"hashed_password": user_create.password} #密码不能存明文，学完JWT认证再来搞定
    )
    logger.debug("用户信息创建完毕")
    session.add(db_obj) #将数据存入暂存区
    session.commit() #提交写入数据库
    session.refresh(db_obj) #刷新
    logger.info("成功将用户信息写入PG")
    return db_obj

#将会话记录写入数据库
def create_conversation(*,session: Session,conv :ConservationCreate) -> Conversation:
    logger.debug("开始创建用户会话记录信息")
    db_conversation = Conversation.model_validate(conv)
    logger.debug("用户会话记录信息创建完毕")
    session.add(db_conversation)
    session.commit()
    session.refresh(db_conversation)
    logger.info("成功将用户会话记录信息写入PG")
    return db_conversation


#处理流式响应的文本
def stream():
    pass

#将大模型消息写入数据库
def create_assistant(*,session: Session,)-> Message:
    logger.debug("开始创建用大模型回复信息")
    db_assistant = Message.model_validate()
    logger.debug("大模型回复信息创建完毕")
    session.add(db_assistant)
    session.commit()
    session.refresh(db_assistant)
    logger.info("成功将大模型回复信息写入PG")
    return db_assistant

#将用户输入消息存入
def create_messages(*,session: Session,msg:MessageCreate) -> Message:
    logger.debug("开始创建用户会消息记录信息")
    db_messages = Message.model_validate(msg)
    logger.debug("用户会消息记录信息创建完毕")
    session.add(db_messages)
    session.commit()
    session.refresh(db_messages)
    logger.info("用户消息已存入PG")
    return db_messages
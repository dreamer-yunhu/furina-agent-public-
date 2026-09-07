"""
处理agent线程的相关业务逻辑
"""
import uuid
from fastapi import HTTPException,status
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.table import User, AgentThreadID
from app.repositories.agent_thread_id import get_thread, create_thread, list_threads, count_threads, delete_thread, \
        rename_thread
from app.schemas.model import ThreadCreate


#归属校验
async def get_owned_threads(
        session: AsyncSession,*,
        current_user:User,
        thread_id:uuid.UUID,
)->AgentThreadID:
        """
        鉴权用的，查不到一律404
        :param session:
        :param current_user:
        :param thread_id:
        :return:
        """
        _thread_id_ = await get_thread(session,thread_id)
        if not _thread_id_ or _thread_id_.user_id != current_user.id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,detail="线程不存在")
        return _thread_id_

#创建线程业务逻辑
async def create_user_thread(
        session: AsyncSession,*,
        current_user:User,
        inform:ThreadCreate
)->AgentThreadID:
    """
    创建线程的具体业务逻辑
    :param inform:
    :param current_user:
    :param session:
    :return:
    """
    return await create_thread(
            session,
            user_id=current_user.id,
            title=inform.title
    )

#返回用户线程数函数
async def list_user_threads(
        session: AsyncSession,*,
        current_user:User,
        page: int = 1,
        size: int = 20,
)->dict:
        """
        返回用户所有线程
        :param session:
        :param current_user:
        :param page:
        :param size:
        :return:
        """
        items = await list_threads(session,user_id=current_user.id,page=page,size=size)
        total = await count_threads(session,user_id=current_user.id)
        return {"items": items, "total": total, "page": page, "size": size}

#删除函数
async def delete_user_thread(
        session: AsyncSession,*,
        current_user:User,
        thread_id:uuid.UUID,
        saver:AsyncPostgresSaver
)->None:
    """
    :param saver:
    :param session:
    :param current_user:
    :param thread_id:
    :return:
    """
    #先归属校验
    await get_owned_threads(session,current_user=current_user,thread_id=thread_id)
    #删除
    fact = await delete_thread(session,thread_id=thread_id,saver=saver)
    if not fact:
            await saver.adelete_thread(thread_id=str(thread_id))


#重命名函数
async def rename_user_thread(
        session: AsyncSession,*,
        current_user:User,
        thread_id:uuid.UUID,
        title:str
)->bool:
        """

        :param session:
        :param current_user:
        :param thread_id:
        :param title:
        :return:
        """
        #校验归属再重命名
        await get_owned_threads(session,current_user=current_user,thread_id=thread_id)
        result = await rename_thread(session,thread_id=thread_id,title=title)
        return result





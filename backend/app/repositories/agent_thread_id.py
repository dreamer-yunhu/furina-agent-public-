"""
用于agent的线程id相关事宜
"""
import uuid
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from sqlalchemy import select, func, update
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.table import AgentThreadID


#创建线程
async def create_thread(
        session: AsyncSession,*,
        user_id:uuid.UUID,
        title:str
)->AgentThreadID:
    """
    创建线程
    :param session:数据库会话
    :param user_id: 用户唯一id
    :param title: 线程名称
    :return: 线程的ORM对象
    """
    thread = AgentThreadID(user_id=user_id, title=title)
    session.add(thread)
    await session.commit()
    await session.refresh(thread)
    return thread

#查线程
async def get_thread(session: AsyncSession, thread_id:uuid.UUID)->AgentThreadID|None:
    """
    按照主键查找对应线程是否存在——校验函数
    :param session: 数据库会话
    :param thread_id: 线程id
    :return: 查找到的线程ORM对象
    """
    return (await session.execute(
        select(AgentThreadID).where(AgentThreadID.id == thread_id)
    )).scalar_one_or_none()

#查找并返回用户的所有线程
async def list_threads(
        session: AsyncSession,*,
        user_id:uuid.UUID,
        page: int = 1,
        size: int = 20,
)->list[AgentThreadID]:
    """
    查找并返回用户所有线程，是分页的
    :param session: 数据库会话
    :param user_id: 用户全局唯一id
    :param page: 起始页（起始数据库）
    :param size: 数据数量（跳过和查找的基数）
    :return: 由AgentThreadID对象构成的列表
    """
    stm = (
        select(AgentThreadID)
        .where(AgentThreadID.user_id == user_id) #查找到对应用户的所有数据
        .order_by(AgentThreadID.created_at.desc()) #按照创建时间排序，倒序
        .offset((page - 1) * size) #跳过多少条数据
        .limit(size)) #查找多少条数据
    return (await session.execute(stm)).scalars().all() #返还查找到的所有数据

#统计线程数量
async def count_threads(
        session: AsyncSession,*,
        user_id:uuid.UUID,
):
    """
    统计用户的总线程数量
    :param session: 数据库会话
    :param user_id: 用户全局唯一id
    :return: 统计数量
    """
    return (await session.execute(
        select(func.count()).select_from(AgentThreadID).where(AgentThreadID.user_id == user_id)
    )).scalar_one()

#重命名线程
async def rename_thread(
        session: AsyncSession,*,
        thread_id:uuid.UUID,
        title:str,
)->bool:
    """
    用于重命名线程名称
    :param session: 数据库会话
    :param thread_id: 线程id
    :param title: 线程的新名称
    :return: True/False
    """
    res = await session.execute(
        update(AgentThreadID).where(AgentThreadID.id == thread_id).values(title=title) #更新语句
        #更新等于传入id的线程名称
    )
    await session.commit()
    #最后一行代码确认是否改到行
    return res.rowcount >0

#删除线程
async def delete_thread(
        session: AsyncSession,*,
        thread_id:uuid.UUID,
        saver:AsyncPostgresSaver
)->bool:
    """
    删除对应线程
    :param saver:
    :param session:
    :param thread_id:
    :return:
    """
    #先查要删除的线程是否存在
    thread = await get_thread(session, thread_id)
    if not thread:
        return False
    await saver.adelete_thread(str(thread_id))
    await session.delete(thread)
    await session.commit()
    return True






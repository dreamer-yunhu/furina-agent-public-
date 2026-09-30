"""线程的业务逻辑 + 数据访问（已合并，原 repositories/agent_thread_id.py）。

⚠️ 为什么合并成一个文件（架构调整决定）：
    桌面版是单进程本地应用，线程的数据访问**只有一个消费者**（本文件的业务函数）。
    原来拆成 services + repositories 两层是照抄 web —— 那层的存在理由是
    “多个 service 复用同一份数据访问”，在这里不成立。

    保留分层感：数据访问函数统一加 `db_` 前缀（`db_get_thread` 等），
    读代码时仍能区分“直接读写库的”与“做业务判断的”。
"""

import uuid
from fastapi import HTTPException,status
from sqlalchemy.ext.asyncio import AsyncSession
from furina_core.checkpoint import CheckpointStore
from furina_core.models import User, AgentThreadID
from furina_desktop.api.contracts import ThreadCreate

# ⚠️ AI 改动：原来的 `from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver`
#    已删除 —— 桌面版用 SQLite，且业务层不该依赖具体 saver。
#    查 checkpointer 的依赖应由调用方传入（见 delete_user_thread 的 saver 参数）。
#    这个参数的**类型标注**留给 M4 收尾时改成 furina_core.checkpoint.CheckpointStore。


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
        _thread_id_ = await db_get_thread(session,thread_id)
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
    return await db_create_thread(
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
        items = await db_list_threads(session,user_id=current_user.id,page=page,size=size)
        total = await db_count_threads(session,user_id=current_user.id)
        return {"items": items, "total": total, "page": page, "size": size}

#删除函数
async def delete_user_thread(
        session: AsyncSession,*,
        current_user:User,
        thread_id:uuid.UUID,
        saver:CheckpointStore
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
    fact = await db_delete_thread(session,thread_id=thread_id,saver=saver)
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
        result = await db_rename_thread(session,thread_id=thread_id,title=title)
        return result






# ====================================================================
# 以下为数据访问层（原 repositories，已并入）
# ====================================================================

async def db_create_thread(
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
async def db_get_thread(session: AsyncSession, thread_id:uuid.UUID)->AgentThreadID|None:
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
async def db_list_threads(
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
async def db_count_threads(
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
async def db_rename_thread(
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
async def db_delete_thread(
        session: AsyncSession,*,
        thread_id:uuid.UUID,
        saver:CheckpointStore
)->bool:
    """
    删除对应线程
    :param saver:
    :param session:
    :param thread_id:
    :return:
    """
    #先查要删除的线程是否存在
    thread = await db_get_thread(session, thread_id)
    if not thread:
        return False
    await saver.adelete_thread(str(thread_id))
    await session.delete(thread)
    await session.commit()
    return True






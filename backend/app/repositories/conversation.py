"""
会话表 CRUD：只做持久化，不做业务判断。
外键 user_id 由上层传入（来自 get_current_user 的 current_user.id）。
"""
import uuid
from sqlalchemy import select, func, update
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.table import Conversation


async def create_conversation(
    session: AsyncSession, *,
    user_id: uuid.UUID,     # 外键值：由 service 从 current_user.id 取来
    title: str,
) -> Conversation:
    """创建会话，外键 user_id 必须来自当前登录用户"""
    conv = Conversation(user_id=user_id, title=title)
    session.add(conv)
    await session.commit()
    await session.refresh(conv)
    return conv


async def get_conversation(session: AsyncSession, conversation_id: uuid.UUID) -> Conversation | None:
    """按主键取会话（不校验归属，归属校验放 service 层）"""
    return (await session.execute(
        select(Conversation).where(Conversation.id == conversation_id)
    )).scalar_one_or_none()


async def list_conversations(
    session: AsyncSession, *,
    user_id: uuid.UUID,
    page: int = 1,
    size: int = 20,
) -> list[Conversation]:
    """按用户分页查会话，新→旧"""
    stmt = (select(Conversation)
            .where(Conversation.user_id == user_id)
            .order_by(Conversation.created_at.desc())
            .offset((page - 1) * size)
            .limit(size))
    return list((await session.execute(stmt)).scalars().all())


async def count_conversations(session: AsyncSession, *, user_id: uuid.UUID) -> int:
    """统计某用户的会话总数，配合分页返回 total"""
    return (await session.execute(
        select(func.count()).select_from(Conversation).where(Conversation.user_id == user_id)
    )).scalar_one()


async def rename_conversation(
    session: AsyncSession, *,
    conversation_id: uuid.UUID,
    title: str,
) -> bool:
    """重命名会话，返回是否真的改到了行"""
    res = await session.execute(
        update(Conversation).where(Conversation.id == conversation_id).values(title=title)
    )
    await session.commit()
    return res.rowcount > 0


async def delete_conversation(session: AsyncSession, conversation_id: uuid.UUID) -> bool:
    """
    删除会话。messages 由表级 ON DELETE CASCADE 级联清除（table.py 已配好），
    不用手动删消息。
    """
    conv = await get_conversation(session, conversation_id)
    if not conv:
        return False
    await session.delete(conv)
    await session.commit()
    return True

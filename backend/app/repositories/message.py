"""
消息表 CRUD：只做持久化。
conversation_id 由上层传入（来自查库得到的会话主键）；
role 由服务端决定（服务端明确知道这条消息是谁产生的），不信任客户端传值。
"""
import uuid
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.table import Message
from app.schemas.model import MessageRole


async def save_message(
    session: AsyncSession, *,
    conversation_id: uuid.UUID,   # 外键值：上层查库得到的会话主键
    role: MessageRole,            # 服务端决定：USER 或 ASSISTANT
    content: str,
) -> Message:
    """保存一条消息，role 转成字符串值（"user" / "assistant"）落库"""
    msg = Message(
        conversation_id=conversation_id,
        role=role.value,
        content=content,
    )
    session.add(msg)
    await session.commit()
    await session.refresh(msg)
    return msg


async def list_recent_messages(
    session: AsyncSession, *,
    conversation_id: uuid.UUID,
    limit: int = 30,
) -> list[Message]:
    """
    取该会话最近 limit 条消息，返回时转成时间正序。
    多轮对话直接用它拼上下文；需要历史翻页时再扩展 before_id 游标。
    """
    stmt = (select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.desc(), Message.id.desc())
            .limit(limit))
    rows = list((await session.execute(stmt)).scalars().all())
    return list(reversed(rows))  # 数据库倒序取，反转回时间正序

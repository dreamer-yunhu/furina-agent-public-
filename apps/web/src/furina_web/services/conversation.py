"""
会话业务层：组合 repository，做归属校验等业务判断。
外键 user_id 的来源就在这里——从 current_user.id 取值传给 repository。
"""
import asyncio
asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
import uuid
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from furina_web.models.table import Conversation, User
from furina_web.schemas.contracts import ConversationCreate
from furina_web.repositories.conversation import (
    create_conversation, get_conversation,
    list_conversations, count_conversations,
    delete_conversation,rename_conversation
)


async def create_user_conversation(
    session: AsyncSession, *,
    current_user: User,
    inform: ConversationCreate,
) -> Conversation:
    """创建会话：外键 user_id = current_user.id（来自依赖注入）"""
    return await create_conversation(
        session,
        user_id=current_user.id,
        title=inform.title,
    )


async def list_user_conversations(
    session: AsyncSession, *,
    current_user: User,
    page: int = 1,
    size: int = 20,
) -> dict:
    """某用户的会话列表 + 总数（分页信息）"""
    items = await list_conversations(session, user_id=current_user.id, page=page, size=size)
    total = await count_conversations(session, user_id=current_user.id)
    return {"items": items, "total": total, "page": page, "size": size}


async def get_owned_conversation(
    session: AsyncSession, *,
    current_user: User,
    conversation_id: uuid.UUID,
) -> Conversation:
    """取会话并校验归属：别人的会话一律 404（防越权）"""
    conv = await get_conversation(session, conversation_id)
    if not conv or conv.user_id != current_user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail= "会话不存在")
    return conv


async def delete_user_conversation(
    session: AsyncSession, *,
    current_user: User,
    conversation_id: uuid.UUID,
) -> None:
    """先校验归属再删除（级联清消息）"""
    await get_owned_conversation(session, current_user=current_user, conversation_id=conversation_id)
    await delete_conversation(session, conversation_id)

#定义重命名用户会话名称
async def rename_user_conversation(session:AsyncSession,*,
                                   current_user:User,conversation_id:uuid.UUID,
                                   title:str)->bool:
    #校验归属
    await get_owned_conversation(
        session,
        current_user = current_user,
        conversation_id = conversation_id
    )
    result = await rename_conversation(session,conversation_id=conversation_id,title = title)
    return result
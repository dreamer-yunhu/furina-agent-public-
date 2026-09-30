"""
聊天路由：对话 + 会话管理 + 历史
"""
import uuid
from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from redis import asyncio as aioredis
from furina_core.storage.session import get_session
from furina_web.auth.dependencies import get_current_user
from furina_web.storage.redis_client import get_redis,get_redis_fuse
from furina_core.circuit_breaker import CircuitBreaker as RedisFuse
from furina_core.models import User
from furina_web.schemas.contracts import ChatRequest, ConversationCreate, RenameConversation
from furina_web.services.stream import stream_chat
from furina_web.services.conversation import (
    create_user_conversation, list_user_conversations,
    get_owned_conversation, delete_user_conversation, rename_user_conversation,
)
from furina_web.repositories.message import list_recent_messages

router = APIRouter(prefix="/chat", tags=["聊天"])


@router.post("")
async def chat(request: ChatRequest,
               user:User = Depends(get_current_user),
               session:AsyncSession = Depends(get_session),
               redis:aioredis.Redis = Depends(get_redis),
               fuse:RedisFuse = Depends(get_redis_fuse)
               ):
    cov = await get_owned_conversation(session,current_user=user,conversation_id=uuid.UUID(request.chat_session_id))
    return StreamingResponse(stream_chat(request=request,
                                         session=session,
                                         redis = redis,
                                         fuse = fuse,
                                         conv = cov
                                         ),
                             media_type="text/event-stream"
                             )


#---------- 会话管理（外键 user_id 来自 get_current_user） ----------
@router.post("/conversations")
async def create_conversation(
    body: ConversationCreate,
    current_user: User = Depends(get_current_user),   # 外键值的来源
    session: AsyncSession = Depends(get_session),
):
    conv = await create_user_conversation(session, current_user=current_user, inform=body)
    return {"id": str(conv.id), "title": conv.title, "created_at": conv.created_at}



@router.get("/conversations")
async def list_conversations(
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    return await list_user_conversations(session, current_user=current_user, page=page, size=size)


@router.delete("/conversations/{conversation_id}")
async def delete_conversation(
    conversation_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    await delete_user_conversation(session, current_user=current_user, conversation_id=conversation_id)
    return {"ok": True}

#重命名会话名称路由
@router.patch("/conversations/{conversation_id}")
async def rename_conv(
        new_title: RenameConversation,
        conversation_id: uuid.UUID ,
        current_user = Depends(get_current_user),
        session = Depends(get_session)
):
    await rename_user_conversation(
        session,
        current_user = current_user,
        conversation_id = conversation_id,
        title = new_title.title
    )
    return {"ok":True}






@router.get("/conversations/{conversation_id}/messages")
async def list_messages(
    conversation_id: uuid.UUID,
    limit: int = Query(default=30, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    # 先校验归属，再取历史，防止读别人的会话
    await get_owned_conversation(session, current_user=current_user, conversation_id=conversation_id)
    msgs = await list_recent_messages(session, conversation_id=conversation_id, limit=limit)
    return {
        "messages": [
            {"role": m.role, "content": m.content, "created_at": m.created_at}
            for m in msgs
        ]
    }

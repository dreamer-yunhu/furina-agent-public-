"""
挂载furina-agent所有相关接口
"""
import uuid
from fastapi import APIRouter,Depends,Query
from fastapi.responses import StreamingResponse
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from sqlalchemy.ext.asyncio import AsyncSession
from app.auth.dependencies import get_current_user
from app.core.agent_graph import get_graph, get_saver
from app.core.database import get_session
from app.models.table import User
from app.schemas.model import ThreadCreate, RenameThread, AgentRequest
from app.services.agent_thread import create_user_thread, list_user_threads, delete_user_thread, rename_user_thread, \
    get_owned_threads
from app.services.agent_stream import agent_stream
router = APIRouter(prefix="/agent", tags=["agent"])
@router.post("")
async def agent_chat(
        inform:AgentRequest,
        graph = Depends(get_graph),
        current_user:User = Depends(get_current_user),
        session:AsyncSession = Depends(get_session),
):
    await get_owned_threads(
        session,
        current_user = current_user,
        thread_id=inform.chat_thread_id
    )
    return StreamingResponse(
        agent_stream(
            graph = graph,
            inform = inform,
        ),
        media_type="text/event-stream"
    )

@router.get("/resume")
async def resume_chat():
    pass



@router.post("/threads")
async def create_thread(
        body:ThreadCreate,
        session:AsyncSession = Depends(get_session),
        current_user:User = Depends(get_current_user)
):
    result = await create_user_thread(
        session,
        current_user = current_user,
        inform=body
    )
    return {"id": str(result.id), "title": result.title, "created_at": result.created_at}

@router.get("/threads")
async def list_threads(
        page: int = Query(default=1, ge=1),
        size: int = Query(default=20, ge=1, le=100),
        session:AsyncSession = Depends(get_session),
        current_user:User = Depends(get_current_user)
):
    return await list_user_threads(
        session,
        current_user = current_user,
        page = page,
        size = size,
    )

@router.delete("/threads/{thread_id}")
async def delete_thread(
        thread_id: uuid.UUID,
        session:AsyncSession = Depends(get_session),
        current_user:User = Depends(get_current_user),
        saver:AsyncPostgresSaver = Depends(get_saver)
):
    await delete_user_thread(
        session,
        current_user = current_user,
        thread_id = thread_id,
        saver = saver
    )
    return {"ok":True}

@router.patch("/threads/{thread_id}")
async def update_thread(
        body:RenameThread,
        thread_id:uuid.UUID,
        session:AsyncSession = Depends(get_session),
        current_user:User = Depends(get_current_user),
):
    await rename_user_thread(
        session,
        current_user = current_user,
        thread_id = thread_id,
        title=body.title,
    )
    return {"ok": True}
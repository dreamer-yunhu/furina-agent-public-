"""桌面版的 agent 路由。

⚠️ AI 改动（本轮）：import 与类型标注去掉了 PG 依赖 ——
    原来 `from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver`
    是为 `saver: AsyncPostgresSaver = Depends(get_saver)` 那个标注用的。
    桌面版现在用 SQLite，标注改为 `furina_core.checkpoint.CheckpointStore` 协议 ——
    这样路由**只依赖协议，不依赖任何具体 saver**。
"""
import uuid
from fastapi import APIRouter,Depends,Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from furina_core.checkpoint import CheckpointStore
from furina_core.storage.session import get_session
from furina_core.models import User
from furina_desktop.auth import get_local_user as get_current_user
from furina_desktop.agent.build import get_graph
from furina_desktop.storage.lifespan import get_saver
from furina_desktop.api.contracts import ThreadCreate, RenameThread, AgentRequest
from furina_desktop.services.agent_thread import create_user_thread, list_user_threads, delete_user_thread, rename_user_thread, \
    get_owned_threads
from furina_desktop.agent.stream import agent_stream
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
        saver:CheckpointStore = Depends(get_saver)
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
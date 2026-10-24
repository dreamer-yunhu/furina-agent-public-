"""桌面版的 agent 路由。

⚠️ AI 改动（本轮）：import 与类型标注去掉了 PG 依赖 ——
    原来 `from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver`
    是为 `saver: AsyncPostgresSaver = Depends(get_saver)` 那个标注用的。
    桌面版现在用 SQLite，标注改为 `furina_core.checkpoint.CheckpointStore` 协议 ——
    这样路由**只依赖协议，不依赖任何具体 saver**。
"""
import uuid
from fastapi import APIRouter,Depends,HTTPException,Query,status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from furina_core.checkpoint import CheckpointStore
from furina_core.storage.session import get_session
from furina_core.models import User
from furina_desktop.auth import get_local_user as get_current_user
from furina_desktop.agent.build import get_graph
from furina_desktop.storage.lifespan import get_saver
from furina_desktop.api.contracts import ThreadCreate, RenameThread, AgentRequest, AgentResumeRequest
from furina_desktop.services.agent_thread import create_user_thread, list_user_threads, delete_user_thread, rename_user_thread, \
    get_owned_threads
from furina_desktop.agent.stream import (
    DecisionMismatch,
    agent_resume_stream,
    agent_stream,
    check_decision_matches,
    get_pending_tool_call_ids,
)
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

# ── AI 改动：原先是 `@router.get("/resume") -> pass`（返回 200 空串，
#    前端会以为审批成功）。现改为 POST + 先校验再流式续跑。
#    复核重点：三条 409 判据（归属 / 是否挂起 / 决定是否逐条对齐）——
#    任何一条漏掉，都可能把审批结果套到别的线程或别的批次上。
@router.post("/resume")
async def resume_chat(
        body: AgentResumeRequest,
        graph=Depends(get_graph),
        current_user: User = Depends(get_current_user),
        session: AsyncSession = Depends(get_session),
):
    # ① 线程归属：查不到一律 404（与首次对话同一口径，不泄漏"存在但属于别人"）
    await get_owned_threads(
        session,
        current_user=current_user,
        thread_id=body.chat_thread_id,
    )

    config = {"configurable": {"thread_id": str(body.chat_thread_id)}}

    # ② 图确实处于 interrupt（不是"用户随便 POST 一个 resume"）
    pending = await get_pending_tool_call_ids(graph=graph, config=config)
    if not pending:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="该会话当前没有待审批的操作",
        )

    # ③ 决定必须与待审项一一对应：少了会永远挂起，多了是伪造/串批
    try:
        check_decision_matches(body.review, pending)
    except DecisionMismatch as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        )

    return StreamingResponse(
        agent_resume_stream(
            graph=graph,
            chat_thread_id=body.chat_thread_id,
            decision=body.review,
        ),
        media_type="text/event-stream",
    )



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
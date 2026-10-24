"""桌面版的 agent 路由。

⚠️ AI 改动（本轮）：import 与类型标注去掉了 PG 依赖 ——
    原来 `from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver`
    是为 `saver: AsyncPostgresSaver = Depends(get_saver)` 那个标注用的。
    桌面版现在用 SQLite，标注改为 `furina_core.checkpoint.CheckpointStore` 协议 ——
    这样路由**只依赖协议，不依赖任何具体 saver**。
"""
import uuid
from fastapi import APIRouter,Depends,HTTPException,Query,Request,status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from furina_core.checkpoint import CheckpointStore
from furina_core.task.decision_service import DecisionOutcome
from furina_core.task.enums import ApprovalStatus
from furina_core.task.resume_service import ResumeOutcome
from furina_core.storage.session import get_session
from furina_core.models import User
from furina_desktop.auth import get_local_user as get_current_user
from furina_desktop.agent.build import get_graph
from furina_desktop.agent.contracts import ReviewAction
from furina_desktop.agent.runtime import (
    AgentRuntime,
    DecisionInput,
    DecisionScopeError,
    PreflightError,
    ThreadBusy,
)
from furina_desktop.storage.lifespan import get_saver
from furina_desktop.api.contracts import (
    AgentDecisionRequest,
    AgentRequest,
    AgentResumeRequest,
    RenameThread,
    ThreadCreate,
)
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


def get_agent_runtime(request: Request) -> AgentRuntime:
    """从 lifespan 注入的运行时适配器取 session factory。"""
    runtime = getattr(request.app.state, "agent_runtime", None)
    if runtime is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="运行时未初始化",
        )
    return runtime


_OK_DECISION = {DecisionOutcome.APPLIED, DecisionOutcome.IDEMPOTENT}


def _to_decision_inputs(items) -> list[DecisionInput]:
    """把 HTTP/图契约里的决定转成 runtime 输入（状态机仍归 T20）。"""
    out: list[DecisionInput] = []
    for item in items:
        raw_approval = getattr(item, "approval_id", None)
        approval_id = None
        if raw_approval:
            try:
                approval_id = uuid.UUID(str(raw_approval))
            except ValueError as exc:
                raise HTTPException(
                    status_code=422,
                    detail="approval_id 不是合法的 UUID",
                ) from exc
        out.append(
            DecisionInput(
                decision=(
                    ApprovalStatus.APPROVED
                    if item.action == ReviewAction.APPROVE
                    else ApprovalStatus.REJECTED
                ),
                approval_id=approval_id,
                tool_call_id=getattr(item, "tool_call_id", None),
                reason=getattr(item, "reason", None),
            )
        )
    return out


def _decision_results_payload(results) -> list[dict]:
    return [
        {
            "approval_id": str(item.approval_id) if item.approval_id else None,
            "tool_call_id": item.tool_call_id,
            "outcome": item.outcome.value,
            "late": item.late,
        }
        for item in results
    ]


def _raise_for_resume(result) -> None:
    """T22 结果 → HTTP。RESUMED 之外一律不恢复图。"""
    if result.outcome is ResumeOutcome.RESUMED:
        return
    detail = {
        "code": result.outcome.value,
        "failure_code": result.failure_code.value if result.failure_code else None,
    }
    if result.outcome in (ResumeOutcome.NOT_FOUND, ResumeOutcome.SCOPE_MISMATCH):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)
    raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)


def _raise_for_decision_results(results) -> None:
    """非 APPLIED/IDEMPOTENT → 明确 HTTP 错误，且不启动图恢复。"""
    failed = [item for item in results if item.outcome not in _OK_DECISION]
    if not failed:
        return
    payload = _decision_results_payload(results)
    if any(
        item.outcome in (DecisionOutcome.NOT_FOUND, DecisionOutcome.SCOPE_MISMATCH)
        for item in failed
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "decision_scope_mismatch", "results": payload},
        )
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={"code": "decision_conflict", "results": payload},
    )


@router.post("")
async def agent_chat(
        inform:AgentRequest,
        graph = Depends(get_graph),
        runtime: AgentRuntime = Depends(get_agent_runtime),
        current_user:User = Depends(get_current_user),
        session:AsyncSession = Depends(get_session),
):
    await get_owned_threads(
        session,
        current_user = current_user,
        thread_id=inform.chat_thread_id
    )

    # T23：先创建 Task/Execution，图现场键 = execution.graph_thread_id。
    try:
        run = await runtime.start_run(
            thread_id=inform.chat_thread_id,
            instruction=inform.user_input,
        )
    except ThreadBusy as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "thread_busy",
                "message": "该会话已有进行中的执行",
                "execution_id": str(exc.execution_id),
                "status": exc.status,
            },
        )

    return StreamingResponse(
        agent_stream(
            graph = graph,
            inform = inform,
            run = run,
            runtime = runtime,
        ),
        media_type="text/event-stream"
    )

@router.post("/decisions")
async def submit_agent_decisions(
        body: AgentDecisionRequest,
        runtime: AgentRuntime = Depends(get_agent_runtime),
        current_user: User = Depends(get_current_user),
        session: AsyncSession = Depends(get_session),
):
    """T23-3：持久化审批决定（调用 T20），**不恢复图**。

    恢复仍由 `/agent/resume` 完成；两步分开，便于前端先落库再续跑。
    """
    await get_owned_threads(
        session,
        current_user=current_user,
        thread_id=body.chat_thread_id,
    )

    for item in body.decisions:
        if item.approval_id is None and not item.tool_call_id:
            raise HTTPException(
                status_code=422,
                detail="每条决定必须提供 approval_id 或 tool_call_id",
            )

    execution = await runtime.active_execution(body.chat_thread_id)
    if execution is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="该会话当前没有可审批的执行",
        )

    try:
        results = await runtime.submit_decisions(
            thread_id=body.chat_thread_id,
            execution_id=execution.id,
            decisions=_to_decision_inputs(body.decisions),
            decided_by=str(current_user.id),
        )
    except DecisionScopeError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        )

    _raise_for_decision_results(results)
    return {
        "execution_id": str(execution.id),
        "results": _decision_results_payload(results),
    }


# ── AI 改动：原先是 `@router.get("/resume") -> pass`（返回 200 空串，
#    前端会以为审批成功）。现改为 POST + 先校验再流式续跑。
#    复核重点：三条 409 判据（归属 / 是否挂起 / 决定是否逐条对齐）——
#    任何一条漏掉，都可能把审批结果套到别的线程或别的批次上。
@router.post("/resume")
async def resume_chat(
        body: AgentResumeRequest,
        graph=Depends(get_graph),
        runtime: AgentRuntime = Depends(get_agent_runtime),
        current_user: User = Depends(get_current_user),
        session: AsyncSession = Depends(get_session),
):
    # ① 线程归属：查不到一律 404（与首次对话同一口径，不泄漏"存在但属于别人"）
    await get_owned_threads(
        session,
        current_user=current_user,
        thread_id=body.chat_thread_id,
    )

    # ② T23：图现场键来自活动 Execution，不再拿业务会话 id 猜。
    execution = await runtime.active_execution(body.chat_thread_id)
    if execution is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="该会话当前没有可恢复的执行",
        )
    config = {"configurable": {"thread_id": execution.graph_thread_id}}

    # ② 图确实处于 interrupt（不是"用户随便 POST 一个 resume"）
    try:
        pending = await get_pending_tool_call_ids(graph=graph, config=config)
    except Exception as exc:  # noqa: BLE001 —— 读不到 checkpoint ≠ 状态不一致
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "checkpoint_unavailable", "error": str(exc)},
        ) from exc
    if not pending:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "state_mismatch", "reason": "graph_not_interrupted"},
        )

    # ③ 决定必须与待审项一一对应：少了会永远挂起，多了是伪造/串批
    try:
        check_decision_matches(body.review, pending)
    except DecisionMismatch as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        )

    # T23-3：先持久化决定（T20），再恢复图。
    # 重复提交同一决定 → IDEMPOTENT；相反决定 → 409；不存在的审批 → 404。
    # 这样不会出现“工具已执行、审批仍 PENDING”的状态。
    try:
        results = await runtime.submit_decisions(
            thread_id=body.chat_thread_id,
            execution_id=execution.id,
            decisions=_to_decision_inputs(body.review.decisions),
            decided_by=str(current_user.id),
        )
    except DecisionScopeError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        )
    _raise_for_decision_results(results)

    # T23-4：先做 DB ↔ 图双向预检，再由 T22 校验并成对迁移到 RUNNING。
    # 两步任一失败都不调用图。
    allow_rejected = any(
        item.action == ReviewAction.REJECT for item in body.review.decisions
    )
    try:
        resume_result, batch_ids = await runtime.prepare_resume(
            graph=graph,
            config=config,
            thread_id=body.chat_thread_id,
            execution_id=execution.id,
            allow_rejected=allow_rejected,
        )
    except PreflightError as exc:
        if exc.code == "checkpoint_unavailable":
            http_code = status.HTTP_503_SERVICE_UNAVAILABLE
        elif exc.code == "not_found":
            http_code = status.HTTP_404_NOT_FOUND
        else:
            http_code = status.HTTP_409_CONFLICT
        raise HTTPException(
            status_code=http_code, detail={"code": exc.code, **exc.detail}
        )
    _raise_for_resume(resume_result)

    return StreamingResponse(
        agent_resume_stream(
            graph=graph,
            graph_thread_id=execution.graph_thread_id,
            decision=body.review,
            execution_id=execution.id,
            runtime=runtime,
            approval_ids=batch_ids,
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
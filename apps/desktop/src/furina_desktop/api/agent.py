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
    get_owned_threads, list_thread_executions, list_user_tasks, list_user_approvals
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

# ── AI 新增：任务 / 审批列表（待人工复核）──
# 复核重点：
#   1. 列表一律**按当前用户过滤**（桌面版只有一个本地用户，但接口形状不该依赖这点）。
#   2. `instruction` 可能很长，列表只回前 200 字；完整内容走详情，别把大字段塞进列表。
#   3. 审批列表不带 `args_json`（可能含大段文件内容），只给路径与状态。
@router.get("/tasks")
async def list_agent_tasks(
        page: int = Query(default=1, ge=1),
        size: int = Query(default=20, ge=1, le=100),
        session: AsyncSession = Depends(get_session),
        current_user: User = Depends(get_current_user),
):
    rows, total = await list_user_tasks(
        session,
        user_id=current_user.id,
        page=page,
        size=size,
    )
    items = [
        {
            "id": str(task.id),
            "thread_id": str(task.thread_id),
            "thread_title": thread_title,
            "instruction": (task.instruction or "")[:200],
            "status": task.status,
            "created_at": task.created_at,
            "updated_at": task.updated_at,
        }
        for task, thread_title in rows
    ]
    return {"items": items, "total": total, "page": page, "size": size}


@router.get("/approvals")
async def list_agent_approvals(
        page: int = Query(default=1, ge=1),
        size: int = Query(default=20, ge=1, le=100),
        status_filter: str | None = Query(default=None, alias="status"),
        thread_id: uuid.UUID | None = Query(default=None),
        session: AsyncSession = Depends(get_session),
        current_user: User = Depends(get_current_user),
):
    if status_filter is not None and status_filter not in {
        item.value for item in ApprovalStatus
    }:
        raise HTTPException(
            status_code=422,  # 与文件内其它参数校验保持一致的写法，避免 starlette 弃用警告
            detail=f"未知的审批状态: {status_filter}",
        )

    rows, total = await list_user_approvals(
        session,
        user_id=current_user.id,
        approval_status=status_filter,
        thread_id=thread_id,
        page=page,
        size=size,
    )
    items = [
        {
            "id": str(approval.id),
            "task_id": str(approval.task_id),
            "execution_id": str(approval.execution_id),
            "thread_id": str(execution_thread_id),
            "thread_title": thread_title,
            "tool_name": approval.tool_name,
            "target_path": approval.target_path,
            "approval_status": approval.approval_status,
            "tool_execution_status": approval.tool_execution_status,
            "created_at": approval.created_at,
            "decided_at": approval.decided_at,
            "decision_reason": approval.decision_reason,
        }
        for approval, execution_thread_id, thread_title in rows
    ]
    return {"items": items, "total": total, "page": page, "size": size}


# ── AI 新增：会话历史（待人工复核）──
# 复核重点：历史**不是一张消息表**，而是每个 Execution 各自的 checkpoint。
#   所以这里必须按 thread → executions（时间正序）逐段读 state.messages，
#   任何"只读最后一次执行"的简化都会让历史缺段。
_ROLE_BY_TYPE = {
    "human": "user",
    "ai": "assistant",
    "tool": "tool",
    "system": "system",
}


def _message_text(content) -> str:
    """LangChain 的 content 可能是 str，也可能是 [{type: text, ...}] 片段列表。"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict) and part.get("type") == "text":
                parts.append(str(part.get("text", "")))
        return "".join(parts)
    return str(content)


@router.get("/threads/{thread_id}/messages")
async def list_thread_messages(
        thread_id: uuid.UUID,
        graph=Depends(get_graph),
        session: AsyncSession = Depends(get_session),
        current_user: User = Depends(get_current_user),
):
    """读取会话历史。

    只回传**有文本内容**的消息：纯 tool_call 的 AI 消息 content 为空，
    前端目前没有渲染那种气泡，硬塞进去会得到空行。
    """
    await get_owned_threads(
        session,
        current_user=current_user,
        thread_id=thread_id,
    )

    executions = await list_thread_executions(session, thread_id=thread_id)

    items: list[dict] = []
    for execution in executions:
        snapshot = await graph.aget_state(
            {"configurable": {"thread_id": execution.graph_thread_id}}
        )
        values = getattr(snapshot, "values", None) or {}
        segment: list[dict] = []
        for message in values.get("messages", []):
            role = _ROLE_BY_TYPE.get(getattr(message, "type", ""))
            text = _message_text(getattr(message, "content", ""))
            if role is None or not text.strip():
                continue
            segment.append(
                {
                    "id": str(getattr(message, "id", "") or ""),
                    "role": role,
                    "content": text,
                    "name": getattr(message, "name", None),
                    "execution_id": str(execution.id),
                }
            )

        # ★ chat 子图的回复不在根 messages 里：它写在子图自己的 chat_messages，
        #   同时把纯文本结果回填到根 state 的 `result`（见 agent/nodes/chat.py）。
        #   所以历史必须把 `result` 当作本轮助手回复补进来，否则只剩用户的话。
        result_text = (values.get("result") or "").strip()
        already = segment and segment[-1]["role"] == "assistant" and segment[-1]["content"] == result_text
        if result_text and not already:
            segment.append(
                {
                    "id": "",
                    "role": "assistant",
                    "content": result_text,
                    "name": None,
                    "execution_id": str(execution.id),
                    "from_result": True,
                }
            )

        items.extend(segment)

    return {"items": items, "total": len(items)}


@router.get("/threads/{thread_id}/pending")
async def get_thread_pending(
        thread_id: uuid.UUID,
        graph=Depends(get_graph),
        session: AsyncSession = Depends(get_session),
        current_user: User = Depends(get_current_user),
):
    """查询该会话当前是否停在审批中断上。

    用途：刷新页面后恢复审批卡。没有它，用户一刷新就再也看不到那个中断，
    只能重新发起（而旧中断还挂在 checkpoint 里）。
    只看最近一次执行 —— 更早的执行都已经结束。
    """
    await get_owned_threads(
        session,
        current_user=current_user,
        thread_id=thread_id,
    )

    executions = await list_thread_executions(session, thread_id=thread_id)
    for execution in reversed(executions):
        snapshot = await graph.aget_state(
            {"configurable": {"thread_id": execution.graph_thread_id}}
        )
        interrupts = getattr(snapshot, "interrupts", None) or ()
        if not interrupts:
            continue
        first = interrupts[0]
        value = first.value if isinstance(first.value, dict) else {}
        return {"pending": {"interrupt_id": first.id, "review": value}}

    return {"pending": None}


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
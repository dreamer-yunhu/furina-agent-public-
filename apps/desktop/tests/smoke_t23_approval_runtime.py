"""T23-2 验收：审批先落库、再 interrupt，且绑定到 Execution 图现场。

# ── AI-ASSISTED ── 本文件由 AI 生成，待人工复核 ──
# 类型：真实 SQLite 业务库 + 真实 SQLite checkpoint + 真实 LangGraph + Fake LLM。
# 不是 Mock：审批行、Task/Execution 状态、checkpoint 的 thread_id 都查库断言。

跑法（仓库根）：
    .venv-build\\Scripts\\python.exe apps\\desktop\\tests\\smoke_t23_approval_runtime.py
"""

from __future__ import annotations

import asyncio
import shutil
import sqlite3
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "apps" / "desktop" / "src"))
sys.path.insert(0, str(ROOT / "packages" / "core" / "src"))

from langchain_core.messages import AIMessage, HumanMessage  # noqa: E402
from sqlalchemy import event, select  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402
from sqlmodel import SQLModel  # noqa: E402

from furina_core.config import settings  # noqa: E402
from furina_core.models import AgentThreadID, User  # noqa: E402
from furina_core.task.enums import (  # noqa: E402
    ApprovalStatus,
    ExecutionStatus,
    TaskStatus,
    ToolExecutionStatus,
)
from furina_core.task.models import AgentExecution, AgentTask, ApprovalRequest  # noqa: E402
from furina_core.task import repository  # noqa: E402
from furina_core.task.lifecycle_service import transition_pair  # noqa: E402
from furina_core.task.service import compute_args_hash  # noqa: E402
from furina_desktop.agent.build import build_graph  # noqa: E402
from furina_desktop.agent.runtime import (  # noqa: E402
    AgentRuntime,
    ApprovalDraft,
    DecisionInput,
    ApprovalSetupError,
    ThreadBusy,
    set_runtime,
)
import furina_desktop.agent.nodes.coder as coder_mod  # noqa: E402
from furina_desktop.agent.tools.registry import read_file_tool, write_file_tool  # noqa: E402
from furina_desktop.storage.local_store import SqliteCheckpointStore  # noqa: E402

PASS, FAIL = "PASS", "FAIL"
_results: list[tuple[str, bool]] = []


def check(label: str, ok: bool, extra: str = "") -> None:
    _results.append((label, ok))
    print(f"  [{PASS if ok else FAIL}] {label}" + (f"   {extra}" if extra else ""))


class FakeModel:
    def __init__(self, tool_calls: list[dict]) -> None:
        self.tool_calls = tool_calls
        self.calls = 0

    async def ainvoke(self, messages):
        self.calls += 1
        if self.calls == 1 and self.tool_calls:
            return AIMessage(content="", tool_calls=self.tool_calls)
        return AIMessage(content="完成")


async def make_env(tmp: Path):
    tmp.mkdir(parents=True, exist_ok=True)
    engine = create_async_engine(f"sqlite+aiosqlite:///{(tmp / 'business.db').as_posix()}")

    @event.listens_for(engine.sync_engine, "connect")
    def _fk(dbapi_connection, _record):
        cur = dbapi_connection.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

    user_id = uuid.uuid4()
    thread_id = uuid.uuid4()
    async with factory() as session:
        session.add(User(id=user_id, user_name="t23", hashed_password=""))
        await session.commit()
        session.add(AgentThreadID(id=thread_id, title="t23", user_id=user_id))
        await session.commit()

    store = SqliteCheckpointStore(tmp / "checkpoints.sqlite")
    await store.open()
    runtime = AgentRuntime(factory, workspace_root=tmp / "sandbox", approval_timeout_seconds=600)
    set_runtime(runtime)
    return engine, factory, store, runtime, thread_id, user_id


async def graph_state(factory, task_id):
    async with factory() as session:
        task = await session.get(AgentTask, task_id)
        execution = (
            await session.execute(
                select(AgentExecution).where(AgentExecution.task_id == task_id)
            )
        ).scalars().first()
        approvals = (
            await session.execute(
                select(ApprovalRequest).where(ApprovalRequest.execution_id == execution.id)
            )
        ).scalars().all()
    return task, execution, approvals


async def main() -> None:
    tmp = ROOT / "_smoke_tmp" / "t23_runtime"
    if tmp.exists():
        shutil.rmtree(tmp, ignore_errors=True)
    box = tmp / "sandbox"
    box.mkdir(parents=True)
    (box / "readme.txt").write_text("hello", encoding="utf-8")
    settings.sandbox_root = box
    read_file_tool.root_dir = str(box)
    write_file_tool.root_dir = str(box)

    engine, factory, store, runtime, thread_id, user_id = await make_env(tmp)
    graph = build_graph(store)
    try:
        print("=== 1. 安全工具：运行收尾为 COMPLETED，无审批行 ===")
        coder_mod.llm_with_tools = FakeModel(
            [{"name": "read_file_tool", "args": {"file_path": "readme.txt"}, "id": "call_safe"}]
        )
        run = await runtime.start_run(thread_id=thread_id, instruction="read")
        check("graph key = execution id", run.graph_thread_id == str(run.execution_id))
        config = {"configurable": {"thread_id": run.graph_thread_id}}
        await graph.ainvoke(
            {
                "messages": [HumanMessage(content="read")],
                "mode": "code",
                "subagent_task": "read",
                "task_id": str(run.task_id),
                "execution_id": str(run.execution_id),
            },
            config,
        )
        await runtime.finalize_run(run.execution_id, status="completed")
        task, execution, approvals = await graph_state(factory, run.task_id)
        check("task COMPLETED", task.status == TaskStatus.COMPLETED.value, task.status)
        check("execution COMPLETED", execution.status == ExecutionStatus.COMPLETED.value, execution.status)
        check("no approval rows", len(approvals) == 0)

        print("\n=== 2. 高风险管理：先落库，再 interrupt ===")
        coder_mod.llm_with_tools = FakeModel(
            [{"name": "write_file_tool",
              "args": {"file_path": "out.txt", "text": "approved!"},
              "id": "call_w1"}]
        )
        thread2 = uuid.uuid4()
        async with factory() as session:
            session.add(AgentThreadID(id=thread2, title="t23-2", user_id=user_id))
            await session.commit()
        run2 = await runtime.start_run(thread_id=thread2, instruction="write")
        cfg2 = {"configurable": {"thread_id": run2.graph_thread_id}}
        await graph.ainvoke(
            {
                "messages": [HumanMessage(content="write")],
                "mode": "code",
                "subagent_task": "write",
                "task_id": str(run2.task_id),
                "execution_id": str(run2.execution_id),
            },
            cfg2,
        )
        snap = await graph.aget_state(cfg2)
        check("graph interrupted", len(snap.interrupts) == 1)
        payload = snap.interrupts[0].value if snap.interrupts else {}
        requests = payload.get("requests") or []
        check("payload carries one request", len(requests) == 1)
        task2, execution2, approvals2 = await graph_state(factory, run2.task_id)
        check("task WAITING_APPROVAL", task2.status == TaskStatus.WAITING_APPROVAL.value, task2.status)
        check("execution WAITING_APPROVAL",
              execution2.status == ExecutionStatus.WAITING_APPROVAL.value, execution2.status)
        check("one approval row", len(approvals2) == 1, str(len(approvals2)))
        row = approvals2[0] if approvals2 else None
        check("approval PENDING", row is not None and row.approval_status == ApprovalStatus.PENDING.value)
        check("payload approval_id = DB id", requests and requests[0].get("approval_id") == str(row.id),
              f"{requests[0].get('approval_id') if requests else None} / {row.id if row else None}")
        check("args_hash matches", row is not None and row.args_hash == compute_args_hash(
            {"file_path": "out.txt", "text": "approved!"}))
        check("deadline in future", row is not None and row.deadline_at.replace(tzinfo=UTC) > datetime.now(UTC))

        print("\n=== 3. 重试同一批：幂等，不新增 ===")
        draft = ApprovalDraft(
            tool_call_id="call_w1",
            tool_name="write_file_tool",
            args={"file_path": "out.txt", "text": "approved!"},
            target_path="out.txt",
            old_hash=None,
        )
        handles = await runtime.ensure_approvals(
            task_id=run2.task_id, execution_id=run2.execution_id, drafts=[draft]
        )
        _t, _e, approvals_again = await graph_state(factory, run2.task_id)
        check("still one row", len(approvals_again) == 1)
        check("same approval id", handles["call_w1"].approval_id == row.id)

        print("\n=== 4. 同 execution 同 tool_call 改参数：冲突 ===")
        bad = ApprovalDraft(
            tool_call_id="call_w1",
            tool_name="write_file_tool",
            args={"file_path": "out.txt", "text": "DIFFERENT"},
            target_path="out.txt",
            old_hash=None,
        )
        conflict = False
        try:
            await runtime.ensure_approvals(
                task_id=run2.task_id, execution_id=run2.execution_id, drafts=[bad]
            )
        except ApprovalSetupError:
            conflict = True
        check("ApprovalConflict surfaced as setup error", conflict)

        print("\n=== 5. 同会话第二次 /agent：ThreadBusy ===")
        busy = False
        try:
            await runtime.start_run(thread_id=thread2, instruction="again")
        except ThreadBusy:
            busy = True
        check("second run blocked", busy)

        print("\n=== 6. checkpoint 真实落在 execution.graph_thread_id 下 ===")
        con = sqlite3.connect(tmp / "checkpoints.sqlite")
        rows = {r[0] for r in con.execute("SELECT DISTINCT thread_id FROM checkpoints")}
        con.close()
        check("checkpoint key present", run2.graph_thread_id in rows, str(rows))
        check("business thread id NOT used as key", str(thread2) not in rows, str(rows))

        print("\n=== 7. 一批两个高风险调用 → 两行审批 ===")
        thread3 = uuid.uuid4()
        async with factory() as session:
            session.add(AgentThreadID(id=thread3, title="t23-3", user_id=user_id))
            await session.commit()
        coder_mod.llm_with_tools = FakeModel([
            {"name": "write_file_tool", "args": {"file_path": "a.txt", "text": "A"}, "id": "call_a"},
            {"name": "write_file_tool", "args": {"file_path": "b.txt", "text": "B"}, "id": "call_b"},
        ])
        run3 = await runtime.start_run(thread_id=thread3, instruction="two writes")
        cfg3 = {"configurable": {"thread_id": run3.graph_thread_id}}
        await graph.ainvoke(
            {
                "messages": [HumanMessage(content="two writes")],
                "mode": "code",
                "subagent_task": "two writes",
                "task_id": str(run3.task_id),
                "execution_id": str(run3.execution_id),
            },
            cfg3,
        )
        snap3 = await graph.aget_state(cfg3)
        reqs3 = (snap3.interrupts[0].value.get("requests") if snap3.interrupts else []) or []
        _t3, _e3, approvals3 = await graph_state(factory, run3.task_id)
        check("payload has two requests", len(reqs3) == 2, str(len(reqs3)))
        check("two approval rows", len(approvals3) == 2, str(len(approvals3)))
        check("ids unique", len({r.id for r in approvals3}) == 2)
        check("payload ids match DB",
              {r.get("approval_id") for r in reqs3} == {str(a.id) for a in approvals3})
        print("\n=== 8. 整批认领：第二次认领失败 ===")
        dv = [
            DecisionInput(
                decision=ApprovalStatus.APPROVED,
                approval_id=row.id,
                tool_call_id=row.tool_call_id,
            )
            for row in approvals3
        ]
        await runtime.submit_decisions(
            thread_id=thread3,
            execution_id=run3.execution_id,
            decisions=dv,
            decided_by="test",
        )
        ids3 = [row.id for row in approvals3]
        first_claim = await runtime.claim_batch(ids3)
        second_claim = await runtime.claim_batch(ids3)
        check("first claim succeeds", first_claim)
        check("second claim rejected", not second_claim)

        print("\n=== 9. 恢复失败且未开始执行 → SUSPENDED ===")
        thread4 = uuid.uuid4()
        async with factory() as session:
            session.add(AgentThreadID(id=thread4, title="t23-4", user_id=user_id))
            await session.commit()
        coder_mod.llm_with_tools = FakeModel([
            {"name": "write_file_tool", "args": {"file_path": "c.txt", "text": "C"}, "id": "call_c"}
        ])
        run4 = await runtime.start_run(thread_id=thread4, instruction="write c")
        cfg4 = {"configurable": {"thread_id": run4.graph_thread_id}}
        await graph.ainvoke(
            {
                "messages": [HumanMessage(content="write c")],
                "mode": "code",
                "subagent_task": "write c",
                "task_id": str(run4.task_id),
                "execution_id": str(run4.execution_id),
            },
            cfg4,
        )
        async with factory() as session:
            await transition_pair(
                session,
                task_id=run4.task_id,
                execution_id=run4.execution_id,
                task_from=TaskStatus.WAITING_APPROVAL,
                task_to=TaskStatus.RUNNING,
                execution_from=ExecutionStatus.WAITING_APPROVAL,
                execution_to=ExecutionStatus.RUNNING,
            )
        await runtime.handle_resume_failure(run4.execution_id)
        _t4, e4, _a4 = await graph_state(factory, run4.task_id)
        check("suspended after resume failure", e4.status == ExecutionStatus.SUSPENDED.value, e4.status)

        print("\n=== 10. 恢复失败且已开始执行 → FAILED（不挂起） ===")
        async with factory() as session:
            await transition_pair(
                session,
                task_id=run3.task_id,
                execution_id=run3.execution_id,
                task_from=TaskStatus.WAITING_APPROVAL,
                task_to=TaskStatus.RUNNING,
                execution_from=ExecutionStatus.WAITING_APPROVAL,
                execution_to=ExecutionStatus.RUNNING,
            )
        await runtime.handle_resume_failure(run3.execution_id)
        _t3b, e3b, a3b = await graph_state(factory, run3.task_id)
        check("failed after started", e3b.status == ExecutionStatus.FAILED.value, e3b.status)
        check("started status preserved",
              all(row.tool_execution_status == "RUNNING" for row in a3b),
              str([row.tool_execution_status for row in a3b]))
        print("\n=== 11. 恢复失败补偿只看当前批次 ===")
        thread5 = uuid.uuid4()
        async with factory() as session:
            session.add(AgentThreadID(id=thread5, title="t23-5", user_id=user_id))
            await session.commit()
        coder_mod.llm_with_tools = FakeModel([
            {"name": "write_file_tool", "args": {"file_path": "d.txt", "text": "D"}, "id": "call_d"},
            {"name": "write_file_tool", "args": {"file_path": "e.txt", "text": "E"}, "id": "call_e"},
        ])
        run5 = await runtime.start_run(thread_id=thread5, instruction="two writes")
        cfg5 = {"configurable": {"thread_id": run5.graph_thread_id}}
        await graph.ainvoke(
            {
                "messages": [HumanMessage(content="two writes")],
                "mode": "code",
                "subagent_task": "two writes",
                "task_id": str(run5.task_id),
                "execution_id": str(run5.execution_id),
            },
            cfg5,
        )
        _t5, _e5, approvals5 = await graph_state(factory, run5.task_id)
        await runtime.submit_decisions(
            thread_id=thread5,
            execution_id=run5.execution_id,
            decisions=[
                DecisionInput(decision=ApprovalStatus.APPROVED,
                              approval_id=row.id, tool_call_id=row.tool_call_id)
                for row in approvals5
            ],
            decided_by="test",
        )
        await runtime.claim_batch([approvals5[0].id])
        async with factory() as session:
            await repository.finish_tool_execution(
                session, approval_id=approvals5[0].id,
                status=ToolExecutionStatus.SUCCEEDED, result="old batch",
            )
            await transition_pair(
                session,
                task_id=run5.task_id,
                execution_id=run5.execution_id,
                task_from=TaskStatus.WAITING_APPROVAL,
                task_to=TaskStatus.RUNNING,
                execution_from=ExecutionStatus.WAITING_APPROVAL,
                execution_to=ExecutionStatus.RUNNING,
            )
        await runtime.handle_resume_failure(
            run5.execution_id, approval_ids=[approvals5[1].id]
        )
        _t5b, e5b, _a5b = await graph_state(factory, run5.task_id)
        check("scoped compensation SUSPENDED", e5b.status == ExecutionStatus.SUSPENDED.value, e5b.status)
    finally:
        set_runtime(None)
        await store.close()
        await engine.dispose()

    passed = sum(1 for _, ok in _results if ok)
    print(f"\n{passed}/{len(_results)} passed")
    if passed != len(_results):
        print("failed:")
        for label, ok in _results:
            if not ok:
                print("  -", label)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())

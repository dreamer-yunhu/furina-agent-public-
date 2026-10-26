"""T23 冒烟测试的共享夹具：临时业务库 + AgentRuntime + 线程。

只在测试进程里用；不进产品代码。
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

from langchain_core.messages import AIMessage
from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

import furina_desktop.agent.nodes.supervisor as supervisor_mod
from furina_core.models import AgentThreadID, User
from furina_desktop.agent.runtime import AgentRuntime, set_runtime


# ── AI 新增（Stage A）：主管意图节点的测试替身 ──
# 为什么所有图级测试都要装它：加了 intent_node 之后，任何 `graph.ainvoke(...)`
# 都会先调意图模型 —— 不装替身就会真连网，测试变成"看运气"。
# 手法与既有 `coder_mod.llm_with_tools = FakeModel(...)` 一致（模块级变量 + 赋值）。
class FakeIntent:
    """固定输出的假意图模型。

    `script` 可按顺序给出多次输出（用于重试/非法格式用例）；脚本用尽后重复最后一条。
    """

    def __init__(self, intent: str = "CODE", script: list[str] | None = None) -> None:
        self.intent = intent
        self.script = list(script or [])
        self.calls = 0
        self.inputs: list[list] = []

    async def ainvoke(self, messages):
        self.calls += 1
        self.inputs.append(list(messages))
        if self.script:
            text = self.script.pop(0) if len(self.script) > 1 else self.script[0]
        else:
            text = json.dumps({"intent": self.intent, "reason": "test"})
        return AIMessage(content=text)


def install_intent(intent: str = "CODE", script: list[str] | None = None) -> FakeIntent:
    """把主管意图模型换成替身，返回它以便断言调用次数。"""
    model = FakeIntent(intent=intent, script=script)
    supervisor_mod.intent_llm = model
    return model


# ── AI 新增（第二轮审计 D6）：没装替身就**立刻报错**，而不是静默连网 ──
# 历史事故：smoke_t23_decision_api 忘了装意图替身 → intent_node 调真模型 →
# 路由失败 → 等不到 approval_required，表现为 StopIteration（原因藏在很下游）。
# 现在导入本模块即把意图模型换成 fail-fast 桩；用例开头再 install_intent(...) 覆盖。
# 复核重点：这是**测试进程内的副作用**，只在 `_t23_testkit`（测试专用模块）里做，
# 不要把它搬进产品代码。
class _IntentNotInstalled:
    async def ainvoke(self, messages):
        raise RuntimeError(
            "测试未安装意图替身：请在用例开头调用 install_intent(...)，"
            "否则会真的连网（第二轮审计 D6）。"
        )


supervisor_mod.intent_llm = _IntentNotInstalled()


async def make_runtime(root: Path, *, sandbox: Path, timeout: int = 600):
    """建 SQLite 业务库、seed 用户、返回 (engine, factory, runtime, user_id)。"""
    root.mkdir(parents=True, exist_ok=True)
    engine = create_async_engine(f"sqlite+aiosqlite:///{(root / 'business.db').as_posix()}")

    @event.listens_for(engine.sync_engine, "connect")
    def _fk(dbapi_connection, _record):
        cur = dbapi_connection.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

    user_id = uuid.uuid4()
    async with factory() as session:
        session.add(User(id=user_id, user_name=f"t23-{user_id.hex[:8]}", hashed_password=""))
        await session.commit()

    runtime = AgentRuntime(factory, workspace_root=sandbox, approval_timeout_seconds=timeout)
    set_runtime(runtime)
    return engine, factory, runtime, user_id


async def new_thread(factory, user_id: uuid.UUID, title: str = "t23") -> uuid.UUID:
    thread_id = uuid.uuid4()
    async with factory() as session:
        session.add(AgentThreadID(id=thread_id, title=title, user_id=user_id))
        await session.commit()
    return thread_id


def run_input(instruction: str, run) -> dict:
    """主管图入口输入。

    # <- AI 改动（Stage A · D-SUP-04/05）：去掉了 `mode` 与直传的 `subagent_task`。
    唯一权威输入是 `task_input`；`subagent_task` 由 validate_intent_node 按意图映射产生。
    """
    # <- AI 改动（第二轮审计 D4）：不再在这里重置 `intent_attempts`。
    #    轮次边界在图内（`begin_turn_node`），调用方只管给权威输入。
    return {
        "messages": [{"role": "user", "content": instruction}],
        "task_input": instruction,
        "task_id": str(run.task_id),
        "execution_id": str(run.execution_id),
    }


def config_for(run) -> dict:
    return {"configurable": {"thread_id": run.graph_thread_id}}

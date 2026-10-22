"""Thread → Task → Execution → ApprovalRequest 的表模型。

设计要点：

1. **Task 与 Execution 是两层，不是一层。**
   一个业务任务可以因为校验失败被重新委派；每次委派都有自己的 Execution。
   旧 Task / Execution / Approval 全部保留，用于审计。

2. **Execution 持有 LangGraph 的运行 key。**
   `graph_thread_id` 是本方案里唯一传给 `configurable.thread_id` 的值。
   业务 `thread_id` 只做分组，绝不直接当 checkpoint key ——
   否则同一线程的多个任务会共用现场。

3. **审批是执行级，不是线程级。**
   `ApprovalRequest.execution_id` 必填；新 Execution 必然产生新审批，
   旧授权不会因为"同一个线程/同一个任务"被继承。
"""

# ── AI-ASSISTED ── 本文件由 AI 生成/改写，待人工复核 ──
# 复核重点：
#   1. 表名显式指定为 `agent_task` / `agent_execution` / `approval_request`，
#      不要依赖 SQLModel 默认的 `agenttask` 之类命名。
#   2. `graph_thread_id` 用 UNIQUE：一个 Execution 只能对应一个 LangGraph 现场。
#      如果你将来想复用现场，必须先想清楚 resume 如何区分。
#   3. `redelegation_key` 允许 NULL。SQLite 和 PG 都允许多个 NULL 并存，
#      所以初始任务（非重委派）不会互相冲突；只有失败重委派才写这个键。
#   4. 这里没有 Relationship 导航属性 —— 跨表查询一律显式 join/select。
#      理由与 core/models.py 相同：避免 mapper 配置期的跨模块前向引用。

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, Index
from sqlmodel import DateTime, Field, SQLModel, Text

from furina_core.models import get_datetime_utc
from furina_core.task.enums import (
    ApprovalStatus,
    ExecutionStatus,
    TaskStatus,
    ToolExecutionStatus,
)


def _in_clause(values) -> str:
    """把枚举值拼成 SQL IN 列表。只用于固定的类定义，不接收用户输入。"""
    return ", ".join(f"'{v.value}'" for v in values)


class AgentTask(SQLModel, table=True):
    """主管分配的一次业务任务。"""

    __tablename__ = "agent_task"
    __table_args__ = (
        CheckConstraint(
            f"status IN ({_in_clause(TaskStatus)})",
            name="ck_agent_task_status",
        ),
        Index("ix_agent_task_thread_status", "thread_id", "status"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    thread_id: uuid.UUID = Field(
        foreign_key="agentthreadid.id",
        nullable=False,
        index=True,
        ondelete="CASCADE",
    )
    instruction: str = Field(sa_type=Text)
    status: str = Field(default=TaskStatus.QUEUED.value, max_length=32)
    parent_task_id: uuid.UUID | None = Field(
        default=None,
        foreign_key="agent_task.id",
        nullable=True,
    )
    failure_reason: str | None = Field(default=None, sa_type=Text)
    # 只有"由失败触发的重委派"才写；UNIQUE 保证同一失败事件最多建一个子任务。
    redelegation_key: str | None = Field(default=None, max_length=64, unique=True)
    created_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),
    )
    updated_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),
    )


class AgentExecution(SQLModel, table=True):
    """Coder 子图的一次内部执行流程。"""

    __tablename__ = "agent_execution"
    __table_args__ = (
        CheckConstraint(
            f"status IN ({_in_clause(ExecutionStatus)})",
            name="ck_agent_execution_status",
        ),
        Index("ix_agent_execution_task_status", "task_id", "status"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    task_id: uuid.UUID = Field(
        foreign_key="agent_task.id",
        nullable=False,
        index=True,
        ondelete="CASCADE",
    )
    status: str = Field(default=ExecutionStatus.CREATED.value, max_length=32)
    # ★ 传给 LangGraph 的 configurable.thread_id。默认等于 execution_id。
    graph_thread_id: str = Field(max_length=64, unique=True, index=True)
    checkpoint_id: str | None = Field(default=None, max_length=128)
    validation_failure_reason: str | None = Field(default=None, sa_type=Text)
    created_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),
    )
    finished_at: datetime | None = Field(
        default=None,
        sa_type=DateTime(timezone=True),
    )


class ApprovalRequest(SQLModel, table=True):
    """一次具体工具调用的审批请求。

    一行 = 一个工具调用，不是一批。
    """

    __tablename__ = "approval_request"
    __table_args__ = (
        CheckConstraint(
            f"approval_status IN ({_in_clause(ApprovalStatus)})",
            name="ck_approval_status",
        ),
        CheckConstraint(
            f"tool_execution_status IN ({_in_clause(ToolExecutionStatus)})",
            name="ck_tool_execution_status",
        ),
        Index("ix_approval_task_status", "task_id", "approval_status"),
        Index("ix_approval_status_deadline", "approval_status", "deadline_at"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    task_id: uuid.UUID = Field(
        foreign_key="agent_task.id",
        nullable=False,
        index=True,
        ondelete="CASCADE",
    )
    execution_id: uuid.UUID = Field(
        foreign_key="agent_execution.id",
        nullable=False,
        index=True,
        ondelete="CASCADE",
    )

    tool_call_id: str = Field(max_length=128)
    tool_name: str = Field(max_length=128)
    args_json: str = Field(sa_type=Text)
    args_hash: str = Field(max_length=64)
    target_path: str | None = Field(default=None, max_length=512)
    old_hash: str | None = Field(default=None, max_length=64)

    # ★ 幂等键：包含 execution_id，新执行不会继承旧审批。
    idempotency_key: str = Field(max_length=64, unique=True, index=True)

    deadline_at: datetime = Field(sa_type=DateTime(timezone=True))

    approval_status: str = Field(
        default=ApprovalStatus.PENDING.value, max_length=16
    )
    tool_execution_status: str = Field(
        default=ToolExecutionStatus.NOT_STARTED.value, max_length=16
    )

    decided_by: str | None = Field(default=None, max_length=128)
    decided_at: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))
    decision_reason: str | None = Field(default=None, sa_type=Text)

    execution_started_at: datetime | None = Field(
        default=None, sa_type=DateTime(timezone=True)
    )
    execution_finished_at: datetime | None = Field(
        default=None, sa_type=DateTime(timezone=True)
    )
    execution_result: str | None = Field(default=None, sa_type=Text)
    execution_error: str | None = Field(default=None, sa_type=Text)

    created_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),
    )
    updated_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),
    )

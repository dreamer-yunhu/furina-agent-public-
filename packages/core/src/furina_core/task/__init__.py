"""任务层级模型：Thread → Task → Execution → ApprovalRequest。

本包只放**共享的领域模型与状态枚举**，不依赖任何具体存储后端。
web 与 desktop 各自负责建引擎、建表、跑迁移。

    enums       四套状态机（任务 / 执行 / 审批 / 工具执行）
    models      SQLModel 表
    repository  最小读写与条件状态迁移
"""

# ── AI-ASSISTED ── 本文件由 AI 生成/改写，待人工复核 ──
# 复核重点：包根只做再导出，不 import 具体 app，也不建引擎。

from furina_core.task.enums import (
    ApprovalStatus,
    ExecutionStatus,
    TaskStatus,
    ToolExecutionStatus,
    ValidationFailureCode,
)
from furina_core.task.models import AgentExecution, AgentTask, ApprovalRequest

__all__ = [
    "ApprovalStatus",
    "ExecutionStatus",
    "TaskStatus",
    "ToolExecutionStatus",
    "ValidationFailureCode",
    "AgentTask",
    "AgentExecution",
    "ApprovalRequest",
]

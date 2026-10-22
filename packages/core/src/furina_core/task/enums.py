"""四套状态机 —— 任务、执行、审批、工具执行。

为什么要分成四个枚举，而不是一个 `status`：

    任务状态   回答"主管调度到哪一步了"
    执行状态   回答"Coder 这一次执行到哪一步了"
    审批状态   回答"用户对这个操作做了什么决定"
    工具状态   回答"这个操作实际执行到哪一步了"

任何两个混用，都会出现"批准了就等于执行成功"这类语义错误。
"""

# ── AI-ASSISTED ── 本文件由 AI 生成/改写，待人工复核 ──
# 复核重点：
#   1. 状态值全部**大写**，与用户提供的补充需求文档逐字对应。
#      不要为了 Python 习惯改成小写 —— 数据库 CHECK 约束和 API 契约都依赖这些字面量。
#   2. 超时**不改变审批状态**。审批没有 EXPIRED；超时改的是 Task/Execution 的 SUSPENDED。
#   3. 执行结果不确定用 ToolExecutionStatus.UNKNOWN，不能记成 FAILED。

from __future__ import annotations

from enum import Enum


class _StrEnum(str, Enum):
    """`str, Enum` 的公共基类。

    继承 `str` 是为了让：
      · `json.dumps` 能直接序列化（普通 Enum 会 TypeError）
      · SQLModel 把它当字符串存
      · Pydantic 能按值解析
    """

    def __str__(self) -> str:  # pragma: no cover - 便于日志阅读
        return str(self.value)


class TaskStatus(_StrEnum):
    """业务任务状态（主管视角）。"""

    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    SUSPENDED = "SUSPENDED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"

    @classmethod
    def terminal(cls) -> frozenset["TaskStatus"]:
        return frozenset({cls.COMPLETED, cls.FAILED, cls.CANCELLED})


class ExecutionStatus(_StrEnum):
    """Coder 子图的一次执行流程状态。"""

    CREATED = "CREATED"
    RUNNING = "RUNNING"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    SUSPENDED = "SUSPENDED"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"

    @classmethod
    def terminal(cls) -> frozenset["ExecutionStatus"]:
        return frozenset(
            {cls.VALIDATION_FAILED, cls.COMPLETED, cls.FAILED, cls.CANCELLED}
        )


class ApprovalStatus(_StrEnum):
    """用户对一次具体操作的决定。

    ⚠️ 没有 EXPIRED / CANCELLED：
       超时不改变审批状态；取消任务时用 REVOKED 明确撤销待审批。
    """

    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    REVOKED = "REVOKED"

    @classmethod
    def terminal(cls) -> frozenset["ApprovalStatus"]:
        return frozenset({cls.APPROVED, cls.REJECTED, cls.REVOKED})


class ToolExecutionStatus(_StrEnum):
    """工具实际执行状态。

    `APPROVED`（审批状态）≠ `SUCCEEDED`（本枚举）。
    `UNKNOWN` 表示"可能已产生副作用、但结果不确定"，禁止自动重试。
    """

    NOT_STARTED = "NOT_STARTED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"


class ValidationFailureCode(_StrEnum):
    """恢复前校验失败的机器可读原因 —— 用于重委派幂等键。"""

    APPROVAL_MISMATCH = "APPROVAL_MISMATCH"
    TASK_INVALID = "TASK_INVALID"
    ARGS_MISMATCH = "ARGS_MISMATCH"
    OLD_HASH_MISMATCH = "OLD_HASH_MISMATCH"
    ALREADY_EXECUTED = "ALREADY_EXECUTED"
    CHECKPOINT_MISMATCH = "CHECKPOINT_MISMATCH"

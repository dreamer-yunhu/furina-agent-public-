"""Task / Execution 的生命周期规则（纯函数，无 IO、无数据库）。

# ── AI-ASSISTED ── 本文件由 AI 生成/改写，待人工复核 ──
# 复核重点：
#   1. 两张迁移表就是 T19-1 拍板的业务语义，**不要在别处再写一份**。
#   2. 终态在表里是空集合；`is_legal_*` 对任何 from→to 都按表判断，
#      天然拒绝“终态出”“回退到 QUEUED”。
#   3. 这里只回答“这对配对允不允许”，不回答“现在该不该迁”
#      —— 后者属于 Service（时机、存在性、归属、业务前置条件）。
"""

from __future__ import annotations

from enum import Enum

from furina_core.task.enums import ExecutionStatus, TaskStatus


class TransitionOutcome(str, Enum):
    """迁移结果。Service 对外统一返回它，调用方不必再猜布尔值的含义。"""

    APPLIED = "APPLIED"          # 本次抢到并完成迁移
    ILLEGAL = "ILLEGAL"          # 配对不在迁移表里
    CONFLICT = "CONFLICT"        # 配对合法，但当前状态不是 from（含并发被抢）
    NOT_FOUND = "NOT_FOUND"      # 实体不存在
    SCOPE_MISMATCH = "SCOPE_MISMATCH"  # Execution 不属于给定 Task


# Task：主管视角。回退到 QUEUED 一律不允许。
TASK_TRANSITIONS: dict[TaskStatus, frozenset[TaskStatus]] = {
    TaskStatus.QUEUED: frozenset({TaskStatus.RUNNING, TaskStatus.CANCELLED}),
    TaskStatus.RUNNING: frozenset({
        TaskStatus.WAITING_APPROVAL,
        TaskStatus.COMPLETED,
        TaskStatus.FAILED,
        TaskStatus.CANCELLED,
    }),
    TaskStatus.WAITING_APPROVAL: frozenset({
        TaskStatus.RUNNING,
        TaskStatus.SUSPENDED,
        TaskStatus.CANCELLED,
    }),
    TaskStatus.SUSPENDED: frozenset({
        TaskStatus.RUNNING,
        TaskStatus.FAILED,
        TaskStatus.CANCELLED,
    }),
    TaskStatus.COMPLETED: frozenset(),
    TaskStatus.FAILED: frozenset(),
    TaskStatus.CANCELLED: frozenset(),
}


# Execution：一次执行流程。VALIDATION_FAILED 是终态，重试=新建 Execution。
EXECUTION_TRANSITIONS: dict[ExecutionStatus, frozenset[ExecutionStatus]] = {
    ExecutionStatus.CREATED: frozenset({
        ExecutionStatus.RUNNING,
        ExecutionStatus.CANCELLED,
    }),
    ExecutionStatus.RUNNING: frozenset({
        ExecutionStatus.WAITING_APPROVAL,
        ExecutionStatus.COMPLETED,
        ExecutionStatus.FAILED,
        ExecutionStatus.VALIDATION_FAILED,
        ExecutionStatus.CANCELLED,
    }),
    ExecutionStatus.WAITING_APPROVAL: frozenset({
        ExecutionStatus.RUNNING,
        ExecutionStatus.SUSPENDED,
        ExecutionStatus.CANCELLED,
    }),
    ExecutionStatus.SUSPENDED: frozenset({
        ExecutionStatus.RUNNING,
        ExecutionStatus.FAILED,
        ExecutionStatus.CANCELLED,
    }),
    ExecutionStatus.VALIDATION_FAILED: frozenset(),
    ExecutionStatus.COMPLETED: frozenset(),
    ExecutionStatus.FAILED: frozenset(),
    ExecutionStatus.CANCELLED: frozenset(),
}


def is_legal_task_transition(from_status: TaskStatus, to_status: TaskStatus) -> bool:
    """这对 Task 状态迁移是否被允许（不看数据库现状）。"""
    return to_status in TASK_TRANSITIONS.get(from_status, frozenset())


def is_legal_execution_transition(
    from_status: ExecutionStatus, to_status: ExecutionStatus
) -> bool:
    """这对 Execution 状态迁移是否被允许（不看数据库现状）。"""
    return to_status in EXECUTION_TRANSITIONS.get(from_status, frozenset())


def allowed_task_targets(from_status: TaskStatus) -> frozenset[TaskStatus]:
    """便于 UI/测试枚举某个状态的合法出口。"""
    return TASK_TRANSITIONS.get(from_status, frozenset())


def allowed_execution_targets(from_status: ExecutionStatus) -> frozenset[ExecutionStatus]:
    return EXECUTION_TRANSITIONS.get(from_status, frozenset())

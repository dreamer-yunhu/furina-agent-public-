"""审批请求服务：幂等创建、参数规范化、时间归一化、跨任务校验。

# ── AI-ASSISTED ── 本文件由 AI 生成/改写，待人工复核 ──
# 复核重点：
#   1. `create_or_get_approval` 用 SAVEPOINT + flush 捕获唯一约束冲突。
#      **不要**改成 `try: insert; commit() except IntegrityError: select`
#      —— 实测 commit 失败后 session 进入 PendingRollbackError，后续查询直接炸。
#   2. 幂等键**不含** args_hash（已拍板 Q1）。参数变化必须表现为“同键不同哈希”
#      从而抛 ApprovalConflict，而不是悄悄变成一条新的待审记录。
#   3. 时间统一走 `as_utc`：SQLite 读出来是 naive，按 UTC 解释（已拍板 Q3）。
#   4. 跨任务校验放在这里而不是 database schema（已拍板 Q6）；
#      将来若改成复合外键，这个函数可以退化成纯组装。
#
# 本轮范围（T18）：只做“创建或取回”。不做状态迁移、超时扫描、恢复前校验
# （T19/T20/T21/T22），也不实现 MCP 的审批版本命名空间。
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from furina_core.task.models import AgentExecution, ApprovalRequest


class ApprovalConflict(Exception):
    """幂等键命中，但请求内容与既有记录不一致。

    这不是“重复请求”，而是“同一个位置出现了不同内容” —— 必须让调用方看见。
    """

    def __init__(self, *, idempotency_key: str, differences: list[str]) -> None:
        self.idempotency_key = idempotency_key
        self.differences = differences
        detail = "; ".join(differences) if differences else "未知差异"
        super().__init__(
            f"审批请求冲突（idempotency_key={idempotency_key[:12]}…）：{detail}"
        )


def canonical_args_json(args: Mapping[str, Any]) -> str:
    """把工具参数压成稳定 JSON：键排序、无空格、保留非 ASCII。

    `ensure_ascii=False` 只影响可读性，不影响哈希稳定性（编码固定 UTF-8）。
    """
    return json.dumps(dict(args), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def compute_args_hash(args: Mapping[str, Any]) -> str:
    """参数快照哈希。同一组参数无论键序如何都必须得到同一个值。"""
    return hashlib.sha256(canonical_args_json(args).encode("utf-8")).hexdigest()


def derive_idempotency_key(execution_id: uuid.UUID | str, tool_call_id: str) -> str:
    """一次执行里的一个工具调用 → 一个稳定的 64 位十六进制键。

    不含 args_hash（Q1 拍板）：参数被改动时要能被检出，而不是生成新请求。
    """
    raw = f"{execution_id}:{tool_call_id}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def as_utc(value: datetime | None) -> datetime | None:
    """统一 UTC 语义：naive 视为 UTC，aware 转换到 UTC。

    SQLite 没有时区类型，写入 aware 也会读成 naive。所有比较前必须先过这里，
    否则 `datetime.now(UTC) > deadline_at` 会抛 TypeError（已实测）。
    """
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


async def _get_by_key(session: AsyncSession, key: str) -> ApprovalRequest | None:
    stmt = select(ApprovalRequest).where(ApprovalRequest.idempotency_key == key)
    return (await session.execute(stmt)).scalars().first()


def _ensure_same_request(
    existing: ApprovalRequest,
    *,
    task_id: uuid.UUID,
    execution_id: uuid.UUID,
    tool_name: str,
    args_hash: str,
) -> None:
    """逐项比对“请求身份”。任何一项不同都不能沿用旧批准（Q2 拍板）。"""
    differences: list[str] = []
    if existing.task_id != task_id:
        differences.append(f"task_id 不同（既有 {existing.task_id} → 本次 {task_id}）")
    if existing.execution_id != execution_id:
        differences.append(
            f"execution_id 不同（既有 {existing.execution_id} → 本次 {execution_id}）"
        )
    if existing.tool_name != tool_name:
        differences.append(
            f"tool_name 不同（既有 {existing.tool_name!r} → 本次 {tool_name!r}）"
        )
    if existing.args_hash != args_hash:
        differences.append("args_hash 不同（参数快照已变化）")
    if differences:
        raise ApprovalConflict(
            idempotency_key=existing.idempotency_key,
            differences=differences,
        )


async def create_or_get_approval(
    session: AsyncSession,
    *,
    task_id: uuid.UUID,
    execution_id: uuid.UUID,
    tool_call_id: str,
    tool_name: str,
    args: Mapping[str, Any],
    deadline_at: datetime,
    target_path: str | None = None,
    old_hash: str | None = None,
) -> tuple[ApprovalRequest, bool]:
    """幂等创建审批请求，返回 `(记录, 是否本次新建)`。

    行为：
      · 键不存在 → 新建，返回 `(row, True)`
      · 键存在且身份一致 → 返回 `(row, False)`
      · 键存在但身份不一致 → 抛 `ApprovalConflict`
      · task/execution 不匹配或 execution 不存在 → 抛 `ValueError`

    已知边界（Q5 拍板不做）：本函数内部会 `commit()`，与 repository 现有风格一致。
    因此它不能与调用方的其他待提交改动组合成一个事务。
    """
    execution = await session.get(AgentExecution, execution_id)
    if execution is None:
        raise ValueError(f"execution 不存在：{execution_id}")
    if execution.task_id != task_id:
        raise ValueError(
            "task_id 与 execution 所属任务不一致："
            f"task_id={task_id} / execution.task_id={execution.task_id}"
        )

    args_json = canonical_args_json(args)
    args_hash = compute_args_hash(args)
    key = derive_idempotency_key(execution_id, tool_call_id)

    candidate = ApprovalRequest(
        task_id=task_id,
        execution_id=execution_id,
        tool_call_id=tool_call_id,
        tool_name=tool_name,
        args_json=args_json,
        args_hash=args_hash,
        idempotency_key=key,
        deadline_at=as_utc(deadline_at),
        target_path=target_path,
        old_hash=old_hash,
    )

    try:
        # ★ SAVEPOINT：冲突只回滚这一小段，外层 session 仍可用（实测验证）
        async with session.begin_nested():
            session.add(candidate)
            await session.flush()
    except IntegrityError:
        # 注意：冲突可能来自唯一键，也可能来自外键。只有“按键查得到”才算幂等命中。
        existing = await _get_by_key(session, key)
        if existing is None:
            raise
        _ensure_same_request(
            existing,
            task_id=task_id,
            execution_id=execution_id,
            tool_name=tool_name,
            args_hash=args_hash,
        )
        return existing, False

    await session.commit()
    await session.refresh(candidate)
    return candidate, True

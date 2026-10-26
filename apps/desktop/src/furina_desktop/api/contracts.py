"""桌面版的 HTTP 契约 —— 请求/响应模型。

只放**真正跨进程边界**的类型（请求体）。
审批载荷等图状态类型在 `furina_desktop.agent.contracts`。
"""

from __future__ import annotations

import uuid

from pydantic import BaseModel, Field, field_validator

from furina_desktop.agent.contracts import ReviewAction, ReviewDecision
# ↑ 依赖方向说明：api → agent 已经是既有方向（`api/agent.py` 本来就用 agent.build/stream）；
#   `agent/contracts.py` 不反向依赖 api，所以不会成环。


class AgentRequest(BaseModel):
    # <- AI 改动（第二轮审计 D5）：补 min_length + 空白校验。
    #    原因：`intent_node` 对空 task_input 是 `raise ValueError`（视为编程错误），
    #    而这里原来只限 max_length —— 客户端传 "" 会先建好 Task/Execution，
    #    再以 graph_error 收场，留下一条必然失败的任务记录。
    #    复核重点：校验放 HTTP 层是"用户错误"的正确出口，别去放宽 intent_node 的断言。
    user_input: str = Field(min_length=1, max_length=255)
    chat_thread_id: uuid.UUID
    # ⚠️ 待废：桌面版应由配置决定模型，不由请求指定
    model: str = "deepseek-v4-flash"

    @field_validator("user_input")
    @classmethod
    def _strip_and_reject_blank(cls, value: str) -> str:
        """去首尾空白；只剩空白 → 422。顺带避免把空白原样写进 Task.instruction。"""
        stripped = value.strip()
        if not stripped:
            raise ValueError("user_input 不能只有空白字符")
        return stripped


# 定义创建线程的模型
class ThreadCreate(BaseModel):
    title: str = Field(max_length=255)


# 定义修改线程标题的数据模型
class RenameThread(BaseModel):
    title: str = Field(max_length=255)


# 规定审核字段
# ── AI 新增 ── 待人工复核
# 复核重点：review 直接复用图内契约 `ReviewDecision`（含 type 字段与逐条 decisions），
# 而不是在 HTTP 层再造一个平行结构 —— 否则两处字段一漂移，
# execute_node 的 model_validate 就会静默丢字段。
class AgentResumeRequest(BaseModel):
    """审批恢复请求。前端把 approval_required 事件里的 tool_call_id 原样回传。"""

    chat_thread_id: uuid.UUID
    review: ReviewDecision


# ── T23-3：独立决定接口 ──
class ApprovalDecisionItem(BaseModel):
    """一条审批决定。

    `approval_id` 优先；没有时退回 `tool_call_id`（兼容旧前端）。
    两者都没有 → 422。
    """

    approval_id: uuid.UUID | None = None
    tool_call_id: str | None = Field(default=None, max_length=128)
    action: ReviewAction
    reason: str | None = None


class AgentDecisionRequest(BaseModel):
    chat_thread_id: uuid.UUID
    decisions: list[ApprovalDecisionItem] = Field(min_length=1)

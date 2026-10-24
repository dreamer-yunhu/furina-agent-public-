"""桌面版的 HTTP 契约 —— 请求/响应模型。

只放**真正跨进程边界**的类型（请求体）。
审批载荷等图状态类型在 `furina_desktop.agent.contracts`。
"""

from __future__ import annotations

import uuid

from pydantic import BaseModel, Field

from furina_desktop.agent.contracts import ReviewDecision
# ↑ 依赖方向说明：api → agent 已经是既有方向（`api/agent.py` 本来就用 agent.build/stream）；
#   `agent/contracts.py` 不反向依赖 api，所以不会成环。


class AgentRequest(BaseModel):
    user_input: str = Field(max_length=255)
    chat_thread_id: uuid.UUID
    # ⚠️ 待废：桌面版应由配置决定模型，不由请求指定
    model: str = "deepseek-v4-flash"


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

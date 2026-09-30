"""桌面版的 HTTP 契约 —— 请求/响应模型。

只放**真正跨进程边界**的类型（请求体）。
审批载荷等图状态类型在 `furina_desktop.agent.contracts`。
"""

from __future__ import annotations

import uuid

from pydantic import BaseModel, Field


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

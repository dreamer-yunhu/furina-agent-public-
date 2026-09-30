"""web 专属的表 —— 对话与消息。

⚠️ 这两张表 **desktop 不用**：桌面版把对话历史存在 LangGraph 的 checkpoint 里
（SQLite），没有 Conversation / Message 这套结构。

User 与 AgentThreadID 在 urina_core.models（两边共用）。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlmodel import DateTime, Field, Relationship, SQLModel, Text

from furina_core.models import User, get_datetime_utc
from furina_core.enums import MessageRole

class Conversation(SQLModel, table=True):
    id : uuid.UUID = Field(default_factory=uuid.uuid4,primary_key=True)
    created_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),
    )
    updated_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),
    )
    title : str = Field(max_length=255)
    user_id : uuid.UUID = Field(
        foreign_key="user.id",
        nullable=False,
        ondelete="CASCADE",
        index = True
    )
    user : User = Relationship(back_populates="conversations")
    messages : list['Message'] = Relationship(back_populates="conversation",cascade_delete=True)

#创建存储对话信息表格

class Message(SQLModel, table=True):
    id : uuid.UUID = Field(default_factory=uuid.uuid4,primary_key=True)
    role: str = Field(default=MessageRole.USER.value,max_length=255)
    content: str = Field(sa_type=Text)
    created_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True)
    )
    conversation_id : uuid.UUID = Field(
        foreign_key="conversation.id",
        nullable=False,
        ondelete="CASCADE",
        index = True
    )
    conversation :Conversation = Relationship(back_populates="messages")

#创建存储agent的thread_id的表

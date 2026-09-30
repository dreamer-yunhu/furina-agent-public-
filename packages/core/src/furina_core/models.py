"""共享的表模型 —— web 与 desktop 都要用的实体。

    User            两边都要（web 是多用户；desktop 单用户，但仍需要一个身份记录）
    AgentThreadID   agent 对话线程的元数据（desktop 独有；放 core 是因为
                    它依赖 User 的外键，两者应在同一 metadata 里）

web 专属的表（Conversation / Message）在 urina_web.models.tables。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlmodel import DateTime, Field, Relationship, SQLModel, Text


def get_datetime_utc() -> datetime:
    """时间戳工厂。用 UTC —— 本地时区会让跨机器的时间比较出错。"""
    return datetime.now(UTC)

class User(SQLModel, table=True):
    id : uuid.UUID = Field(default_factory=uuid.uuid4,primary_key=True)
    user_name : str = Field(unique=True)
    created_at : datetime = Field(
        default_factory=get_datetime_utc,
        sa_type= DateTime(timezone=True)
    )
    updated_at : datetime = Field(
        default_factory=get_datetime_utc,
        sa_type= DateTime(timezone=True)
    )
    hashed_password : str = Field(max_length=60)
    personal_preference : str|None = Field(default=None,sa_type=Text)
    conversations : list['Conversation'] = Relationship(back_populates="user",cascade_delete=True)


#创建存储对话记录表格

class AgentThreadID(SQLModel, table=True):
    id : uuid.UUID = Field(default_factory=uuid.uuid4,primary_key=True)
    created_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),
    )
    updated_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),
    )
    title: str = Field(max_length=255)
    user_id: uuid.UUID = Field(
        foreign_key="user.id",
        nullable=False,
        ondelete="CASCADE",
        index=True
    )



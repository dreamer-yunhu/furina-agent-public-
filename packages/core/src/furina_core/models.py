"""共享的表模型 —— web 与 desktop 都要用的实体。

    User            两边都要（web 是多用户；desktop 单用户，但仍需要一个身份记录）
    AgentThreadID   agent 对话线程的元数据（desktop 独有；放 core 是因为
                    它依赖 User 的外键，两者应在同一 metadata 里）

web 专属的表（Conversation / Message）在 furina_web.models.table。
"""

# ── AI-ASSISTED ── 本文件由 AI 生成/改写，待人工复核 ──
# 复核重点（本次修复）：
#   1. ★ 删掉了 `User.conversations` 关系（它原本指向 web 独有的 Conversation）。
#      为什么删：注解 `list['Conversation']` 必须在**定义它的模块**（本文件）的
#      命名空间里解析，而 `Conversation` 在 web 侧 —— 解析不到时 SQLModel 会把
#      整串注解 `list['Conversation']` 当关系目标交给 SQLAlchemy，于是**任何**真实
#      ORM 查询在 configure_mappers 阶段就抛：
#          InvalidRequestError: ... expression "relationship("list['Conversation']")"
#      实测对照：老的单文件表 `backend/app/models/table.py`（四个类同模块）能过，
#      拆包之后 web / desktop 两套导入集都不能过。
#      **代价（请你确认能接受）**：ORM 层的 `user.conversations` 导航没了；
#      数据库层的级联仍在（`ForeignKey(ondelete="CASCADE")` 生成 ON DELETE CASCADE），
#      但 SQLModel `cascade_delete=True` 带来的 delete-orphan 会话级级联没有了。
#      要保留导航属性也不该在 core 里写 web 的类名 —— web 侧自己定义单向关系即可
#      （现在 `Conversation.user` 就是单向的）。
#   2. 本文件仍只放"两边都要"的实体；Conversation / Message 留在 web。

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlmodel import DateTime, Field, SQLModel, Text  # <- AI 改动：不再需要 Relationship


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
    # ← AI 改动：这里原有一行 `conversations: list['Conversation'] = Relationship(...)`，已删除。
    #   复核重点：删它是因为跨包类名解析不了（见文件头第 1 条），不是因为它没用。
    #   如果 web 侧将来需要"查用户的所有会话"，用显式 join/select 查询表达，别再把
    #   外键关系写回共享内核 —— 那样 desktop 会被迫认识一张它没有的表。


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



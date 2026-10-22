"""web 专属的表 —— 对话与消息。

⚠️ 这两张表 **desktop 不用**：桌面版把对话历史存在 LangGraph 的 checkpoint 里
（SQLite），没有 Conversation / Message 这套结构。

User 与 AgentThreadID 在 furina_core.models（两边共用）。
"""

# ── AI-ASSISTED ── 本文件由 AI 生成/改写，待人工复核 ──
# 复核重点（本次修复）：
#   1. ★ `Conversation.user` 从 `Relationship(back_populates="conversations")` 改成
#      **单向** `Relationship()`。因为 core 的 `User.conversations` 已删除
#      （它在 core 里解析不到 web 的类名，会让任何 ORM 查询在 configure_mappers 阶段炸，
#        详见 packages/core/src/furina_core/models.py 文件头）。
#      back_populates 要求两端成对，一端删了另一端必须跟着改，否则 mapper 配置直接报错。
#   2. 行为差异：单向关系**没有** delete-orphan 级联；删除用户时靠数据库的
#      ON DELETE CASCADE（`user_id` 的外键声明）清理会话，不靠 ORM。
#      复核重点：确认你们所有删用户的地方都是真删库行，而不是只从 session 里移除对象。
#   3. ★★ 删掉了 `from __future__ import annotations`（老的单文件表也没有它）。
#      这是「ORM 查不了」的**第二个**独立成因，务必看懂再决定要不要加回来：
#        · 加了它，注解全是字符串，pydantic 要在**本模块命名空间**里求值；
#          `Conversation.messages: list['Message']` 引用的 `Message` 在下面才定义
#          → 求值失败 → 留下 ForwardRef(整串 "list['Message']") → SQLModel 把它原样
#          交给 SQLAlchemy → configure_mappers 抛 InvalidRequestError。
#        · 不加它，`list['Message']` 立刻求值成"list + 字符串 'Message'"
#          → SQLModel 取出字符串交给 SQLAlchemy，**由注册表在 configure_mappers 时按名字解析**，
#          消息在前在后都无所谓（这也正是老树能跑的原因）。
#      结论：**本文件不要加回 `from __future__ import annotations`**；将来加新模型时，
#      如果两个类互相引用，请保持"注解写成字符串、类里不要用未来注解"这个组合。

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
    user : User = Relationship()  # <- AI 改动：单向（原 back_populates="conversations" 的另一端已删）
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

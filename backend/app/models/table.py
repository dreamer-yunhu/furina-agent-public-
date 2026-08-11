from datetime import UTC, datetime
import uuid
from sqlmodel import SQLModel,Field,Relationship,DateTime,Text
from app.schemas.model import MessageRole


#定义工厂函数
def get_datetime_utc() -> datetime:
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
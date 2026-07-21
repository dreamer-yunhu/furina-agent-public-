"""
用于定义数据模型
"""
from datetime import UTC, datetime
import uuid
from sqlmodel import SQLModel,Field,Relationship,DateTime,Text
from pydantic import BaseModel
from enum import Enum

#定义工厂函数
def get_datetime_utc() -> datetime:
    return datetime.now(UTC)


#定义接收数据模型
class ChatRequest(BaseModel):
    model : str = "deepseek-v4-pro"
    max_tokens : int = 1000
    user_input : str
    session_id : str = "default"

#定义枚举模型
class MessageRole(str,Enum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"

#定义创建用户时需要提供的信息模型
class UserCreate(SQLModel):
    user_name : str = Field(max_length=255)
    is_active : bool = True
    is_superuser : bool = False
    password : str = Field(min_length=8,max_length=128)

#定义用户登录信息模型
class UserLogin(SQLModel):
    username : str = Field(max_length=255)
    password : str = Field(min_length=8,max_length=128)

#登录返回模型
class UserOut(SQLModel):
    id : uuid.UUID
    username : str = Field(max_length=255)

class LoginResponse(SQLModel):
    access_token : str = Field(max_length=255)
    token_type: str =Field(max_length=255)
    user : UserOut


#设置找回密码模型
class PasswordReset(SQLModel):
    username : str = Field(max_length=255)

#定义创建会话时需要提供的信息模型
class ConservationCreate(SQLModel):
    title : str = Field(max_length=255)

#定义创建消息的信息模型
class MessageCreate(SQLModel):
    contents : str
    role: MessageRole = Field(default=MessageRole.USER,max_length=255)



#定义用户数据表
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
    personal_preference : str = Field(default=None,max_length=255)
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
    role: MessageRole = Field(default=MessageRole.USER,max_length=255)
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
    conversation :Conversation = Relationship(back_populates="messages",cascade_delete=True)




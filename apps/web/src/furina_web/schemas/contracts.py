"""
用于定义数据模型
"""

import uuid
from pydantic import BaseModel,Field
from enum import Enum,StrEnum
from typing import Literal

from furina_core.enums import MessageRole  # 共享枚举，定义在 core（表模型也要用）



#定义openai SDK接收数据模型
class ChatRequest(BaseModel):
    model : str = "deepseek-v4-flash"
    max_tokens : int = 1000
    user_input : str
    chat_session_id : str

# ⚠️ MessageRole 已移到 furina_core.enums —— 它两边都要用（models/table.py 的 role 列），
#    属于共享原语而不是 web 契约。这里只 import，不再重复定义（否则两处会各自漂移）。

#定义创建用户时需要提供的信息模型
class UserCreate(BaseModel):
    username : str = Field(max_length=255)
    is_active : bool = True
    password : str = Field(min_length=8,max_length=128)
    hobby : str|None = Field(default=None,max_length=255)

#定义更新用户信息需要提供的数据模型
class UserUpdate(BaseModel):
    user_name : str = Field(default=None,max_length=255,min_length=1,alias="username",pattern=r"\S+")
    personal_preference : str|None = Field(default=None,min_length=1,max_length=128,alias="hobby",pattern=r"\S+")

#定义用户登录信息模型
class UserLogin(BaseModel):
    username : str = Field(max_length=255)
    password : str = Field(min_length=8,max_length=128)

#登录返回模型
class UserOut(BaseModel):
    id : str
    username : str = Field(max_length=255)
    session_id : str
    personal_preference: str | None =Field(default=None)



class LoginResponse(BaseModel):
    access_token : str
    refresh_token : str
    user : UserOut


#设置找回密码模型
class PasswordReset(BaseModel):
    username : str = Field(max_length=255)
    new_password : str = Field(min_length=8,max_length=128)

#定义创建会话时需要提供的信息模型
class ConversationCreate(BaseModel):
    title : str = Field(max_length=255)

#定义创建消息的信息模型
class MessageCreate(BaseModel):
    contents : str
    role: MessageRole = Field(default=MessageRole.USER)

#定义校验数据模型
class LoginFormData(BaseModel):
    username: str = Field(min_length=3, max_length=50, pattern=r"^\S+$")
    password: str = Field(min_length=6, max_length=128)

#定义查询大模型对话历史返回模型
class LlmHistory(BaseModel):
    contents : str

#定义接收修改会话标题数据模型
class RenameConversation(BaseModel):
    title : str = Field(max_length=255)

#定义修改线程标题的数据模型
class RefreshTokenRequest(BaseModel):
    refresh_token : str

#定义登出接口获取刷新令牌模型
class LogoutRequest(BaseModel):
    refresh_token : str

#定义创建线程的模型

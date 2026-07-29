"""
用于定义数据模型
"""


from pydantic import BaseModel,Field
from enum import Enum



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
class UserCreate(BaseModel):
    username : str = Field(max_length=255)
    is_active : bool = True
    password : str = Field(min_length=8,max_length=128)
    hobby : str|None = Field(default=None,max_length=255)

#定义用户登录信息模型
class UserLogin(BaseModel):
    username : str = Field(max_length=255)
    password : str = Field(min_length=8,max_length=128)

#登录返回模型
class UserOut(BaseModel):
    id : str
    username : str = Field(max_length=255)
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
class ConservationCreate(BaseModel):
    title : str = Field(max_length=255)

#定义创建消息的信息模型
class MessageCreate(BaseModel):
    contents : str
    role: MessageRole = Field(default=MessageRole.USER,max_length=255)









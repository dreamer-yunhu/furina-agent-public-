"""
用于定义数据模型
"""

import uuid
from pydantic import BaseModel,Field
from enum import Enum,StrEnum
from typing import Literal



#定义openai SDK接收数据模型
class ChatRequest(BaseModel):
    model : str = "deepseek-v4-flash"
    max_tokens : int = 1000
    user_input : str
    chat_session_id : str

#定义agent接收数据模型
class AgentRequest(BaseModel):
    user_input:str = Field(max_length=255)
    chat_thread_id : uuid.UUID
    model:str = "deepseek-v4-flash"
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
class RenameThread(BaseModel):
    title : str = Field(max_length=255)

#定义通过刷新令牌获取新访问令牌的模型
class RefreshTokenRequest(BaseModel):
    refresh_token : str

#定义登出接口获取刷新令牌模型
class LogoutRequest(BaseModel):
    refresh_token : str

#定义创建线程的模型
class ThreadCreate(BaseModel):
    title : str = Field(max_length=255)

#规定审核字段
class ReviewAction(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"

#规定审核载荷
class WritePreview(BaseModel):
    tool_call_id: str #工具调用id
    path: str  # 沙箱相对，不给绝对路径
    is_new_file: bool
    old_hash: str | None   # 新建时为 None，乐观锁——保证文件是提出审核时的内容，如果用户在审核期间改了重审
    added: int
    removed: int
    diff: str

#定义interrupt()返回载荷
class ReviewRequest(BaseModel): # interrupt() 抛出侧
    type: Literal["review_request"] = "review_request"
    action   : Literal["review_request"] = "review_request"
    requests : list[WritePreview] #请求是列表，那么审批也得是逐个审批

#定义Command()接收载荷
class ItemDecision(BaseModel):
    tool_call_id: str       # 关联回 WritePreview
    action: ReviewAction
    reason: str | None

class ReviewDecision(BaseModel): # Command(resume=) 收回侧
    type: Literal["review_decision"] = "review_decision"
    decisions: list[ItemDecision] #实现逐个审批

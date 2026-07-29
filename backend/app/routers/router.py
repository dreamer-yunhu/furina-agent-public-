"""
定义聊天接口的文件
"""
from fastapi import APIRouter,Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_session
from app.schemas.model import ChatRequest, UserCreate,UserLogin,PasswordReset
from app.services.auth import user_register, user_login, password_reset
from app.services.stream import stream_chat




router = APIRouter() #定义路由层
@router.post("/chat")
async def chat(request:ChatRequest):
    return  StreamingResponse(stream_chat(request),media_type="text/event-stream")

@router.post("/register")
async def register(user:UserCreate,session:AsyncSession = Depends(get_session)):
    account = await user_register(user,session)
    return {"user_id":account.id,"username":account.user_name}

@router.post("/login")
async def login(login_data:UserLogin,session:AsyncSession = Depends(get_session)):
    user_data = await user_login(login_data,session)
    return user_data

@router.post("/logout")
async def logout(user:UserLogin,session:AsyncSession = Depends(get_session)):
    pass

@router.post("/update")
async def update(user_update:PasswordReset,session:AsyncSession = Depends(get_session)):
    return await password_reset(user_update,session)

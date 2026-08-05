"""
定义聊天接口的文件
"""
from fastapi import APIRouter,Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_session
from app.auth.dependencies import get_current_user
from app.models.table import User
from app.schemas.model import ChatRequest, UserCreate,UserLogin,PasswordReset
from app.services.user import user_register, user_login, password_reset, get_login_from_form
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
async def login(login_data:UserLogin = Depends(get_login_from_form),session:AsyncSession = Depends(get_session)):
    user_data = await user_login(session = session,inform= login_data  )
    return user_data

@router.post("/logout")
async def logout(user:UserLogin,session:AsyncSession = Depends(get_session)):
    pass

@router.post("/update")
async def update(user_update:PasswordReset,session:AsyncSession = Depends(get_session)):
    return await password_reset(user_update,session)


@router.get("/users/me")
async def read_current_user(
    current_user: User = Depends(get_current_user),  # ← 这一行就是"门禁"
):
    """获取当前登录用户的信息"""
    return {
        "id": str(current_user.id),
        "user_name": current_user.user_name,
        "personal_preference": current_user.personal_preference,
        "created_at": current_user.created_at,
    }

@router.post("/refresh_token")
async def refresh_token(refresh_token:str,session:AsyncSession = Depends(get_session)):
    pass

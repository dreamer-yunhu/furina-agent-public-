"""
认证路由：注册、登录、登出、刷新令牌、修改密码
"""
from redis import asyncio as aioredis
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.auth.dependencies import oauth2_scheme, get_current_user
from app.core.database import get_session
from app.core.redis_client import get_redis
from app.schemas.model import UserCreate, UserLogin, PasswordReset, RefreshTokenRequest, LogoutRequest
from app.services.user import user_register, user_login, password_reset, get_login_from_form, user_logout, user_refresh

router = APIRouter(prefix="/auth", tags=["认证"])


@router.post("/register")
async def register(user: UserCreate, session: AsyncSession = Depends(get_session)):
    account = await user_register(user, session)
    return {"user_id": account.id, "username": account.user_name}


@router.post("/login")
async def login(login_data: UserLogin = Depends(get_login_from_form),
                session: AsyncSession = Depends(get_session),
                redis:aioredis.Redis = Depends(get_redis)
                ):
    return await user_login(session=session, inform=login_data,redis=redis)


@router.post("/logout")
async def logout(*,access_token = Depends(oauth2_scheme),
                 refresh_token:LogoutRequest,
                 redis = Depends(get_redis),
                 ):
    result = await user_logout(access_token=access_token, refresh_token=refresh_token.refresh_token, redis=redis)
    return result


@router.post("/refresh")
async def refresh_token(refresh_token : RefreshTokenRequest,redis:aioredis.Redis = Depends(get_redis)):
    new_access_token = await user_refresh(refresh_token.refresh_token,redis)
    return new_access_token



@router.post("/password")
async def update(user_update: PasswordReset, session: AsyncSession = Depends(get_session)):
    return await password_reset(user_update, session)

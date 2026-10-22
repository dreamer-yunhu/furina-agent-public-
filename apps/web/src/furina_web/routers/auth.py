"""
认证路由：注册、登录、登出、刷新令牌、修改密码
"""

# ── AI-ASSISTED ── 本文件由 AI 生成/改写，待人工复核 ──
# 复核重点（本次修复）：`/refresh` 多了一个 `session` 依赖 —— 因为刷新路径要查库拿用户名
# （core 发令牌时不写 name）。细节与"要不要回退"的说明写在函数上的标记里。
from redis import asyncio as aioredis
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from furina_web.auth.dependencies import oauth2_scheme
from furina_core.storage.session import get_session
from furina_web.storage.redis_client import get_redis, get_redis_fuse
from furina_core.circuit_breaker import CircuitBreaker as RedisFuse
from furina_web.schemas.contracts import UserCreate, UserLogin, PasswordReset, RefreshTokenRequest, LogoutRequest
from furina_web.services.user import user_register, user_login, password_reset, get_login_from_form, user_logout, user_refresh

router = APIRouter(prefix="/auth", tags=["认证"])


@router.post("/register")
async def register(user: UserCreate, session: AsyncSession = Depends(get_session)):
    account = await user_register(user, session)
    return {"user_id": account.id, "username": account.user_name}


@router.post("/login")
async def login(login_data: UserLogin = Depends(get_login_from_form),
                session: AsyncSession = Depends(get_session),
                redis:aioredis.Redis = Depends(get_redis),
                fuse:RedisFuse = Depends(get_redis_fuse)
                ):
    return await user_login(session=session, inform=login_data,redis=redis,fuse=fuse)


@router.post("/logout")
async def logout(*,access_token = Depends(oauth2_scheme),
                 refresh_token:LogoutRequest,
                 redis:aioredis.Redis = Depends(get_redis),
                 fuse:RedisFuse = Depends(get_redis_fuse)
                 ):
    result = await user_logout(access_token=access_token,
                               refresh_token=refresh_token.refresh_token,
                               redis=redis,
                               fuse = fuse
                               )
    return result


@router.post("/refresh")
async def refresh_token(refresh_token : RefreshTokenRequest,
                        redis:aioredis.Redis = Depends(get_redis),
                        fuse:RedisFuse = Depends(get_redis_fuse),
                        session: AsyncSession = Depends(get_session)  # <- AI 改动：user_refresh 要查库拿用户名
                        ):
    # <- AI 改动 ── 复核重点：只是多传一个 session（新增一个 Depends 参数），路由语义不变。
    #    为什么要它：core 发令牌时不写用户名，刷新路径只能查库拿（见 services/user.py 文件头第 3 条）。
    #    如果你不同意"刷新时查一次库"，把这条和 services/user.py 里那次 get_user_by_id 一起回退，
    #    改为在 core 的令牌载荷里写回 name。
    new_access_token = await user_refresh(refresh_token.refresh_token,redis,fuse,session)
    return new_access_token



@router.post("/password")
async def update(user_update: PasswordReset, session: AsyncSession = Depends(get_session)):
    return await password_reset(user_update, session)

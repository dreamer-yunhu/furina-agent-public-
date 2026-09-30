"""
用户资料路由：当前用户信息等
"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio.session import AsyncSession
from furina_web.auth.dependencies import get_current_user
from furina_core.storage.session import get_session
from furina_core.models import User
from furina_web.schemas.contracts import UserUpdate
from furina_web.services.user import user_update

router = APIRouter(prefix="/users", tags=["用户"])


@router.get("/me")
async def read_current_user(
    current_user: User = Depends(get_current_user),  # ← 这一行就是"门禁"
):
    """获取当前登录用户的信息"""
    return {
        "id": str(current_user.id),
        "username": current_user.user_name,
        "hobby": current_user.personal_preference,
        "created_at": current_user.created_at,
    }

@router.patch("/me")
async def current_user_update(
    inform:UserUpdate,
    current_user: User = Depends(get_current_user),
        session:AsyncSession = Depends(get_session),
):
    """
    更新用户的非密码信息
    """
    result = await user_update(current_user,session,inform)
    return result
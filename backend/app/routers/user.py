"""
用户资料路由：当前用户信息等
"""
from fastapi import APIRouter, Depends
from app.auth.dependencies import get_current_user
from app.models.table import User

router = APIRouter(prefix="/users", tags=["用户"])


@router.get("/me")
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

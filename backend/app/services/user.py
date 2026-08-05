import logging
from fastapi import HTTPException,status, Form
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.table import User
from app.repositories.crud import get_user_by_name, user_create, reset_pwd
from app.schemas.model import UserCreate, UserLogin, UserOut, LoginResponse, PasswordReset
from app.core.security import verify_password, create_access_token, create_refresh_token

logger = logging.getLogger(__name__)

async def user_register(inform :UserCreate,session:AsyncSession)->User:
    #查，看看用户表里有没有
    user =await get_user_by_name(session,inform.username)
    if user:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="User already exists")
    #开启用户注册
    new_user = await user_create(session,inform)
    logger.debug("注册功能正常")
    return new_user


async def get_login_from_form(
    username: str = Form(...),   # ← 从 Swagger 的表单里拿用户名
    password: str = Form(...)    # ← 从 Swagger 的表单里拿密码
) -> UserLogin:
    # 这一行会触发 Pydantic 校验（长度、空格等），校验不过自动报 422
    return UserLogin(username=username, password=password)


#开始进行登录操作，密钥分发等待
async def user_login(*,session:AsyncSession,inform :UserLogin):
    user = await get_user_by_name(session,inform.username)
    if not user:
        raise HTTPException(status_code=400, detail="Incorrect username or password")
    #开启登录
    if verify_password(inform.password,user.hashed_password):
        #进行令牌
        access_token = create_access_token(
            user_id = user.id,
            user_name=user.user_name
        )
        #设置刷新令牌
        refresh_token = create_refresh_token(
            user_id = user.id,
            user_name=user.user_name
        )
        print(user.personal_preference)
        return LoginResponse(
                access_token = access_token,
                refresh_token = refresh_token,
                user= UserOut(
                    id = str(user.id),
                    username= user.user_name,
                    personal_preference = user.personal_preference
                )
                )

    else:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Incorrect username or password")

#写更改密码接口
async def password_reset(inform:PasswordReset,session:AsyncSession)->str:
    user = await get_user_by_name(session, inform.username)
    if not user:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="User does not exist")
    #改密码
    result = await reset_pwd(session,inform)
    return result

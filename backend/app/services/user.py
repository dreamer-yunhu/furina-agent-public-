import logging
import time
import uuid
from fastapi import HTTPException,status, Form
from redis import asyncio as aioredis
from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.fuse_helpers import fuse_fail_closed
from app.models.table import User
from app.repositories.redis_user import jwt_block_list, is_blocklisted, register_session, \
    is_current_session, clear_session
from app.repositories.user import get_user_by_name, user_create, reset_pwd
from app.schemas.model import UserCreate, UserLogin, UserOut, LoginResponse, PasswordReset
from app.core.security import verify_password, create_access_token, create_refresh_token,decode_token
from app.core.redis_fuse import RedisFuse, CircuitOpenError


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
async def user_login(*,session:AsyncSession,inform :UserLogin,redis:aioredis.Redis,fuse:RedisFuse):
    user = await get_user_by_name(session,inform.username)
    if not user:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Incorrect username or password")

    #开启登录
    if verify_password(inform.password,user.hashed_password):

        # 发一个全局登录在线有效会话的uuid
        session_id = uuid.uuid4()
        # 登记会话（覆盖旧会话 = 顶号）
        try:
            await fuse_fail_closed(fuse,register_session,redis,str(user.id),str(session_id),action="登记会话id")
        except (RedisError,CircuitOpenError):
            logger.error("登录链路：Redis 挂了——无法把会话登记到redis，向客户端返回 503")
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,detail="服务暂不可用,请稍后再试")

        #进行令牌
        access_token = create_access_token(
            user_id = user.id,
            user_name=user.user_name,
            session_id = session_id
        )
        #设置刷新令牌
        refresh_token = create_refresh_token(
            user_id = user.id,
            user_name=user.user_name,
            session_id=session_id
        )
        #print(user.personal_preference)
        return LoginResponse(
                access_token = access_token,
                refresh_token = refresh_token,
                user= UserOut(
                    id = str(user.id),
                    username= user.user_name,
                    session_id = str(session_id),
                    personal_preference = user.personal_preference
                )
                )

    else:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Incorrect username or password")

#定义用户登出函数
async def user_logout(*,access_token : str,refresh_token:str,redis : aioredis.Redis,fuse:RedisFuse):
    # 解码令牌
    try:#因为访问令牌可能过期，如果过期之后执行登出操作显示登出失败，登出应该是一个无论令牌状况如何都成功的操作
        access_payload = decode_token(access_token)

    except HTTPException:
        access_payload = None

    try:  # 因为刷新令牌可能过期，如果过期之后执行登出操作显示登出失败，登出应该是一个无论令牌状况如何都成功的操作
        refresh_payload = decode_token(refresh_token)

    except HTTPException:
        refresh_payload = None

    #归属校验——执行登出操作的必须是用户本人！
    if access_payload and refresh_payload:
        if access_payload.get("sub") != refresh_payload.get("id"):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,detail="访问和刷新令牌用户id不符合！")
    #把访问令牌加入redis黑名单——令牌存在开启拉黑操作
    if access_payload:
        access_jti =access_payload.get("jti") #获得访问令牌全局uuid
        #校验access_jti
        if not access_jti:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,detail="无效访问令牌")
        access_ttl = max(0,int(access_payload.get("exp",0)) - int(time.time())) #保证时间不为复数
        try:
            await fuse_fail_closed(fuse,jwt_block_list,redis,access_jti,access_ttl,action="拉黑旧访问令牌") #把访问加入redis黑名单
        except (RedisError,CircuitOpenError):
            logger.error("登出链路：Redis 挂了——无法把旧访问令牌加入黑名单，向客户端返回 503")
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,detail="服务暂不可用,请稍后再试")



    #把刷新令牌加入黑名单——令牌存在开启拉黑操作
    if refresh_payload:
        if refresh_payload.get("type") != "refresh":
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,detail="请使用刷新令牌！")
        refresh_jti = refresh_payload.get("jti")
        #校验refresh_token
        if not refresh_jti:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,detail="无效刷新令牌")
        refresh_ttl = max(0,int(refresh_payload.get("exp",0))-int(time.time()))
        try:
            await fuse_fail_closed(fuse,jwt_block_list,redis,refresh_jti,refresh_ttl,action="拉黑旧刷新令牌")
        except (RedisError,CircuitOpenError):
            logger.error("登出链路：Redis 挂了——无法把旧刷新令牌加入黑名单，向客户端返回 503")
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="服务暂不可用,请稍后再试")


    #撤销会话登记（用 access 里的 sub 拿 user_id）
    if access_payload:
        user_id = access_payload.get("sub")
        if user_id:
            try:
                await fuse_fail_closed(fuse,clear_session,redis,user_id,action="撤销会话登记")
            except (RedisError, CircuitOpenError):
                logger.error("登出链路：Redis 挂了——无法撤销会话登记，向客户端返回 503")
                raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="服务暂不可用,请稍后再试")


    #返回结果
    return {"success":True}


#写更改密码接口
async def password_reset(inform:PasswordReset,session:AsyncSession)->bool:
    user = await get_user_by_name(session, inform.username)
    if not user:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="User does not exist")
    #改密码
    result = await reset_pwd(session,inform)
    return result

#定义通过刷新令牌获取新同行令牌函数
async def user_refresh(refresh_token:str,redis: aioredis.Redis,fuse:RedisFuse):
    #1解码
    payload = decode_token(refresh_token)
    #2鉴别token类型
    if payload.get("type",None) != "refresh":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,detail="请使用刷新令牌")
    #发一个新的令牌（刷新，访问）
    user_id =payload.get("id")
    user_name = payload.get("name")
    jti =payload.get("jti")
    session_id = payload.get("session_id")

    #判断用户id是否存在
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,detail="无效用户id！")
    #判断用户名称是否存在
    if not user_name:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,detail="无效用户名称！")
    #判断令牌是否有效——存在
    if not jti:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,detail="无效令牌！")
    #判断会话id是否存在
    if not session_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,detail="无效会话id！")
    #判断当前刷新令牌是否在黑名单中
    try:
        if await fuse_fail_closed(fuse,is_blocklisted,redis,jti,action="判断刷新令牌是否位于黑名单中"):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,detail="令牌位于黑名单中！")
    except (RedisError, CircuitOpenError):
        logger.error("刷新令牌路链：Redis 挂了——无法判断当前刷新令牌是否位于黑名单中，向客户端返回 503")
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="服务暂不可用,请稍后再试")

    #判断会话id是否为当前会话id
    try:
        if not await fuse_fail_closed(fuse,is_current_session,redis,session_id,user_id,action="是否为当前会话id") :
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,detail="会话id与当前会话id不符")
    except (RedisError, CircuitOpenError):
        logger.error("刷新令牌路链：Redis 挂了——无法判断令牌中的会话id是否为当前会话id，向客户端返回 503")
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="服务暂不可用,请稍后再试")
    #不在黑名单发令牌和session是当前的
    access_token = create_access_token(uuid.UUID(user_id),user_name,uuid.UUID(session_id))
    refresh_token = create_refresh_token(uuid.UUID(user_id),user_name,uuid.UUID(session_id))

    #把旧的访问令牌uuid加入redis黑名单
    ttl = max(int(payload.get("exp",0)) - int(time.time()),0)
    try:
        await fuse_fail_closed(fuse,jwt_block_list,redis,jti,ttl,action="把旧的访问令牌拉黑")
    except (RedisError, CircuitOpenError):
        logger.error("刷新令牌路链：Redis 挂了——无法拉黑旧令牌对，向客户端返回 503")
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="服务暂不可用,请稍后再试")
    return {
        "access_token":access_token,
        "refresh_token":refresh_token,
    }




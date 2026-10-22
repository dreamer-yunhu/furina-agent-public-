# ── AI-ASSISTED ── 本文件由 AI 生成/改写，待人工复核 ──
# 复核重点（本次修复）：core 的解码器换了返回类型（dict -> TokenPayload dataclass）
# 并换了异常类型（HTTPException -> TokenError），本文件是**受影响最重**的一个，
# 三件事请逐条复核：
#   1. ★ 所有 `payload.get("xxx")` 已改成属性访问，字段对应关系：
#          .get("type")       -> .token_type
#          .get("jti")        -> .jti
#          .get("session_id") -> .session_id
#          .get("sub")/.get("id") -> .subject   （core 发令牌时 sub 与 id 写同一个值）
#          .get("exp", 0)     -> .expires_at / .remaining_seconds
#      改之前是 AttributeError（'TokenPayload' object has no attribute 'get'）→ 每个请求 500。
#   2. `except HTTPException` 改成 `except TokenError`：不改的话，过期令牌走登出会 500，
#      而登出的既有语义是"无论令牌状况如何都成功"。
#   3. ★★ `user_refresh` 的用户名改为**查数据库**（函数新增 session 参数，路由同步改了）。
#      原因：core 的 `create_token` 刻意不把 user_name 写进载荷，令牌里已经没有 `name`
#      这个契约；原来 `if not user_name: 401` 会让**每一次刷新**都直接 401。
#      另一种修法是把 `name` 加回令牌载荷，我选了查库（用户名以库为准，令牌里的旧值不可信）。
#      **如果你更想少一次查询**，就把这个决策翻过来，代价是重新引入"信任令牌里的用户名"。

import logging
# <- AI 改动：删掉 `import time` —— 原三处 int(time.time()) 已全部换成 TokenPayload.remaining_seconds
import uuid
from fastapi import HTTPException,status, Form
from redis import asyncio as aioredis
from redis.exceptions import RedisError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from furina_core.circuit_policies import fail_closed as fuse_fail_closed
from furina_core.models import User
from furina_web.repositories.redis_user import jwt_block_list, is_blocklisted, register_session, \
    is_current_session, clear_session
# <- AI 改动：get_user_by_id 供 user_refresh 查用户名用
from furina_web.repositories.user import get_user_by_name, user_create, reset_pwd, user_reset, get_other_user_by_name, get_user_by_id
from furina_web.schemas.contracts import UserCreate, UserLogin, UserOut, LoginResponse, PasswordReset, UserUpdate
# <- AI 改动：新增 TokenError（core 不再抛 HTTPException）
from furina_core.security import verify_password, create_access_token, create_refresh_token,decode_token_compat as decode_token, TokenError
from furina_core.circuit_breaker import CircuitBreaker as RedisFuse, CircuitOpenError


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
    # ── AI 改动 ── 复核重点：core 的解码器抛 TokenError，不是 HTTPException。
    #    这两个 except 必须跟着改，否则"过期令牌也能登出成功"这条既有语义会被 500 破坏。
    try:#因为访问令牌可能过期，如果过期之后执行登出操作显示登出失败，登出应该是一个无论令牌状况如何都成功的操作
        access_payload = decode_token(access_token)

    except TokenError:  # <- AI 改动（原 HTTPException）
        access_payload = None

    try:  # 因为刷新令牌可能过期，如果过期之后执行登出操作显示登出失败，登出应该是一个无论令牌状况如何都成功的操作
        refresh_payload = decode_token(refresh_token)

    except TokenError:  # <- AI 改动（原 HTTPException）
        refresh_payload = None

    #归属校验——执行登出操作的必须是用户本人！
    if access_payload and refresh_payload:
        # ── AI 改动 ── 复核重点：原来是 access 的 "sub" 与 refresh 的 "id" 两个键相比；
        #    core 发令牌时 sub/id 写同一个值，解码后统一成 .subject —— 校验依然成立
        #    （两个令牌必须属于同一主体），但"键名不同"这层含义没有了。
        if access_payload.subject != refresh_payload.subject:  # <- AI 改动
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,detail="访问和刷新令牌用户id不符合！")
    #把访问令牌加入redis黑名单——令牌存在开启拉黑操作
    if access_payload:
        access_jti =access_payload.jti  # <- AI 改动：获得访问令牌全局uuid（原 .get("jti")）
        #校验access_jti
        if not access_jti:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,detail="无效访问令牌")
        # ── AI 改动 ── 原 `max(0,int(payload.get("exp",0)) - int(time.time()))`；
        #    TokenPayload.remaining_seconds 就是同一个式子（core 里定义好并注明"拉黑就用它"）。
        access_ttl = access_payload.remaining_seconds  # <- AI 改动  #保证时间不为复数
        try:
            await fuse_fail_closed(fuse,jwt_block_list,redis,access_jti,access_ttl,action="拉黑旧访问令牌") #把访问加入redis黑名单
        except (RedisError,CircuitOpenError):
            logger.error("登出链路：Redis 挂了——无法把旧访问令牌加入黑名单，向客户端返回 503")
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,detail="服务暂不可用,请稍后再试")



    #把刷新令牌加入黑名单——令牌存在开启拉黑操作
    if refresh_payload:
        if refresh_payload.token_type != "refresh":  # <- AI 改动（原 .get("type")）
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,detail="请使用刷新令牌！")
        refresh_jti = refresh_payload.jti  # <- AI 改动（原 .get("jti")）
        #校验refresh_token
        if not refresh_jti:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,detail="无效刷新令牌")
        refresh_ttl = refresh_payload.remaining_seconds  # <- AI 改动（原 .get("exp",0) 现算）
        try:
            await fuse_fail_closed(fuse,jwt_block_list,redis,refresh_jti,refresh_ttl,action="拉黑旧刷新令牌")
        except (RedisError,CircuitOpenError):
            logger.error("登出链路：Redis 挂了——无法把旧刷新令牌加入黑名单，向客户端返回 503")
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="服务暂不可用,请稍后再试")


    #撤销会话登记（用 access 里的 sub 拿 user_id）
    if access_payload:
        user_id = access_payload.subject  # <- AI 改动（原 .get("sub")）
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
# ── AI 改动 ── 复核重点：本函数多了一个 `session` 参数（路由 routers/auth.py 同步改了）。
#    原因见文件头第 3 条：用户名不再从令牌里读，改为查库。
async def user_refresh(refresh_token:str,redis: aioredis.Redis,fuse:RedisFuse,session:AsyncSession):
    #1解码
    # ── AI 改动 ── 复核重点：刷新接口本就该在令牌无效时拒绝，所以这里把 TokenError 翻成 401
    #    （改之前没接住 → 过期刷新令牌会变成 500）。
    try:
        payload = decode_token(refresh_token)
    except TokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="刷新令牌已过期，请重新登录" if exc.kind == "expired" else "无效刷新令牌",
        ) from exc
    #2鉴别token类型
    if payload.token_type != "refresh":  # <- AI 改动（原 payload.get("type", None)）
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,detail="请使用刷新令牌")
    #发一个新的令牌（刷新，访问）
    user_id = payload.subject        # <- AI 改动（原 payload.get("id")）
    jti = payload.jti                # <- AI 改动（原 payload.get("jti")）
    session_id = payload.session_id  # <- AI 改动（原 payload.get("session_id")）

    #判断用户id是否存在
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,detail="无效用户id！")
    #判断令牌是否有效——存在
    if not jti:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,detail="无效令牌！")
    #判断会话id是否存在
    if not session_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,detail="无效会话id！")
    # ── AI 改动 ── 用户名从这里开始不再来自令牌：core 的 create_token **刻意不写 name**
    #    （它连 user_name 参数都丢掉了），所以原来那句 `if not user_name: 401`
    #    会让每一次刷新都失败。改为按 sub 查库。
    #    复核重点（两个判断都是我加的）：① 主体不是合法 uuid → 401 而不是 500；
    #    ② 用户已被删除 → 401。如果你更希望"少一次查询"，就得改 core 把 name 写回令牌。
    try:
        user_uuid = uuid.UUID(str(user_id))
        session_uuid = uuid.UUID(str(session_id))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="无效令牌主体！") from exc
    user = await get_user_by_id(session, user_uuid)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,detail="无效用户名称！")
    user_name = user.user_name
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
    # <- AI 改动：用刚查出来的 user 行（user.id / user.user_name），不再依赖令牌里的 id/name
    access_token = create_access_token(user.id,user.user_name,session_uuid)
    refresh_token = create_refresh_token(user.id,user.user_name,session_uuid)

    #把旧的访问令牌uuid加入redis黑名单
    ttl = payload.remaining_seconds  # <- AI 改动（原 max(int(payload.get("exp",0)) - int(time.time()),0)）
    try:
        await fuse_fail_closed(fuse,jwt_block_list,redis,jti,ttl,action="把旧的访问令牌拉黑")
    except (RedisError, CircuitOpenError):
        logger.error("刷新令牌路链：Redis 挂了——无法拉黑旧令牌对，向客户端返回 503")
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="服务暂不可用,请稍后再试")
    return {
        "access_token":access_token,
        "refresh_token":refresh_token,
    }

async def user_update(user:User,session:AsyncSession,inform:UserUpdate)->dict:
    """
    用于更新用户非密码信息
    :param inform: 用户提供的信息字段
    :param user: 当前用户
    :param session: 数据库会话对象
    :return: 修改后的结果
    """
    #第一步，利用pydantic的特性，把需要修改的字段填充进入修改字典
    update_dict = inform.model_dump(exclude_unset=True)
    if not update_dict:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,detail="No fields to update")
    #校验修改的名称是否同名
    if update_dict.get("user_name",False):
        if await get_other_user_by_name(session,inform.user_name,user.id):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT,detail="User already exists")
    #开始执行更新操作——同时处理竞态窗口问题
    try:
        updated_user = await user_reset(session,user.id,update_dict)
        result = {"username":updated_user.user_name,"hobby":updated_user.personal_preference}
        return result
    except IntegrityError:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,detail="User already exists")






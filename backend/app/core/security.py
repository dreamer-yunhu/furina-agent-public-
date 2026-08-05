"""
用于实现加密密码，JWT认证和哈希密码加密
"""
import uuid
import jwt
import bcrypt
import logging
from datetime import datetime, timedelta, timezone
from fastapi import HTTPException, status
from app.core.config import settings
logger = logging.getLogger(__name__)


#生成哈希密码
def hash_password(password: str):
    #使用加密算法得到哈希密码（比特值）
    hashed_bytes = bcrypt.hashpw(
        password.encode("utf-8"),
        bcrypt.gensalt(rounds=12),
    )
    return hashed_bytes.decode("utf-8")


#定义密码验证函数
def verify_password(plain_password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(
        plain_password.encode("utf-8"),
        hashed_password.encode("utf-8")
    )


#定义JWT令牌生成函数
#1 定义载荷生成函数->payload
def create_jwt(payload: dict, expires_delta: timedelta, token_type: str) -> str:
    """
    定义令牌模板
    :param payload:载荷
    :param expires_delta:过期时间
    :param token_type:令牌类型
    :return:令牌模板
    """
    now = datetime.now(tz=timezone.utc)
    to_encode = payload.copy()  #浅拷贝，防止在添加JWT标准字段时，意外修改了外部传入的原始payload字典，保持函数的纯净性。
    to_encode.update({
        "type": token_type,  #定义令牌类型
        "jti": str(uuid.uuid4()),  #全局唯一id
        "iat": now,  #签发时间
        "exp": now + expires_delta,  #过期时间
    })
    #返还令牌模板
    return jwt.encode(to_encode, settings.jwt_key, algorithm=settings.jwt_algo)


#2 定义访问令牌
def create_access_token(user_id: uuid.UUID, user_name: str) -> str:
    """
    签发访问令牌
    :param user_id: 用户唯一全局uuid
    :param user_name: 用户名
    :return: 返还访问令牌
    """
    token = create_jwt(
        payload={"sub": str(user_id), "name": user_name},
        token_type="access",
        expires_delta=timedelta(seconds=settings.access_token_expire_seconds),
    )
    return token


#3 定义刷新令牌
def create_refresh_token(user_id: uuid.UUID, user_name: str) -> str:
    """
    刷新令牌生成函数
    :param user_id: 用户唯一全局uuid
    :param user_name: 用户名
    :return: 返还刷新令牌
    """
    token_ = create_jwt(
        payload={"id": str(user_id), "name": user_name},
        token_type="refresh",
        expires_delta=timedelta(days=settings.refresh_token_expire_days),
    )

    return token_


#定义解码JWT令牌函数
def decode_token(token: str) -> dict:
    """
    验证并解码JWT令牌
    :param token: JWT令牌
    :return: JWT令牌解码结果
    """
    try:
        token_data = jwt.decode(
            jwt=token,
            key=settings.jwt_key,
            algorithms=settings.jwt_algo
        )
        return token_data
    except jwt.ExpiredSignatureError as e:
        logger.exception("JWT令牌过期", e)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="令牌已过期"
        )
    except jwt.InvalidTokenError as e:
        logger.exception("无效JWT令牌！", e)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效令牌"
        )


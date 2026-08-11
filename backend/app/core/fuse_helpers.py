"""
熔断器管“挡不挡”，助手管之后要干什么
"""
import logging
from redis import RedisError
from fastapi import HTTPException
from app.core.redis_fuse import RedisFuse, CircuitOpenError

logger = logging.getLogger(__name__)

#定义redis熔断器助手函数
async def fuse_fail_closed(fuse:RedisFuse,fn,*args,action:str="redis操作"):
    """
    安全类 redis 操作统一走熔断器：挂了抛 503，绝不静默放行（代码复用）
    用于redis黑名单，挂了都拒绝放行
    :param fuse:redis熔断器
    :param fn:要执行的，涉及redis操作的函数
    :param args:不定长参数
    :param action:redis操作类型
    :return:返回函数执行结果
    """
    try:
        return await fuse(fn,*args)
    except (RedisError,CircuitOpenError):
        logger.warning("Redis 不可用，%s 拒绝执行（fail-closed）", action)
        raise

async def fuse_fail_open(fuse:RedisFuse,fn,default,*args,action:str="redis缓存"):
    """
    缓存类：redis挂了降级返回 default，吞掉继续
    :param fuse: redis熔断器
    :param fn:执行redis缓存操作的相关函数
    :param default:默认值
    :param action:redis操作类型2
    :return:
    """
    try:
        return await fuse(fn,*args)
    except (RedisError,CircuitOpenError):
        logger.warning("Redis 不可用，%s 降级", action)
        return default


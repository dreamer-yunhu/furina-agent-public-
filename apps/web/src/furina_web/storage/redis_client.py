"""
管理redis的启动，关闭
"""

# ── AI-ASSISTED ── 本文件由 AI 生成/改写，待人工复核 ──
# 复核重点（本次修复）：熔断器构造改成全关键字 `RedisFuse(name="redis")` ——
# 原写法 `RedisFuse(redis)` 会在 Redis 连上之后的那一行 TypeError。详见 init_redis 里的标记。
import logging
from redis import asyncio as aioredis
from fastapi import FastAPI,Request
# ⚠️ AI 改动：settings 从 urina_core.config 改为 urina_web.config ——
#    redis_url 是 web 专属字段，已从 core 搬走。
from furina_web.config import settings
from furina_core.circuit_breaker import CircuitBreaker as RedisFuse
#配置日志
logger = logging.getLogger(__name__)

#应用启动时创建redis客户端
async def init_redis(app:FastAPI):
    """
    启动时创建redis连接池并挂载到app.state上
    :param app: FastAPI类实例对象
    :return:
    """
    logger.info("正在初始化redis连接池")
    redis = aioredis.from_url(
        url = settings.require_redis_url(),  # ⚠️ AI 改动：缺失时给可操作的错误，而不是把 None 传下去
        decode_responses = True,
        max_connections = 20,
        socket_timeout = 5.0
    )
    await redis.ping() #测试
    #准备熔断器
    # ── AI 改动 ── 复核重点：core 的 `CircuitBreaker.__init__` 是**全关键字**参数
    #    (`def __init__(self, *, name, fail_threshold, ...)`)，原来写的 `RedisFuse(redis)`
    #    会在这一行直接 TypeError —— 而它排在 `await redis.ping()` **之后**，
    #    所以"Redis 没起来"的错误先发生，把这个 bug 掩盖了；Redis 一起来就炸。
    #    熔断器不再持有 redis 客户端（core 里它是纯状态机，下游调用由 __call__ 传入）。
    redis_fuse = RedisFuse(name="redis")  # <- AI 改动（原 RedisFuse(redis)）
    app.state.redis = redis #挂载
    app.state.redis_fuse = redis_fuse #挂载熔断器
    logger.info("redis连接池已就绪")


#应用关闭时关闭redis连接池
async def close_redis(app:FastAPI):
    """
    关闭app时释放redis连接池
    :param app: FastAPI类实例对象
    :return:
    """
    redis = getattr(app.state,"redis",None)#getattr()方法，用于获取某个特定对象的特定属性值，找不到可以设置默认值，防止报错
    if redis:
        await redis.close()
        logger.info("redis连接池已关闭")

#获取全局redis客户端
async def get_redis(request:Request)->aioredis.Redis:
    """
    依赖注入：从app.state获取全局唯一redis客户端
    :param request:
    :return:
    """
    return request.app.state.redis

#获取全局熔断器
async def get_redis_fuse(request:Request)->RedisFuse:
    """
    依赖注入：从app.state获取全局唯一redis熔断器
    :param request:
    :return:
    """
    return request.app.state.redis_fuse

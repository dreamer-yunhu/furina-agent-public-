"""
管理redis的启动，关闭
"""
import logging
from redis import asyncio as aioredis
from fastapi import FastAPI,Request
from app.core.config import settings

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
    redis = await aioredis.from_url(
        url = settings.redis_url,
        decode_responses = True,
        max_connections = 20,
        socket_timeout = 5.0
    )
    await redis.ping() #测试
    app.state.redis = redis #挂载
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


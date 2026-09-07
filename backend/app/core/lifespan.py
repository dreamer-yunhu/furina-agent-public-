"""
lifespan生命周期
"""
import logging
from contextlib import asynccontextmanager
from app.core.redis_client import init_redis,close_redis
from app.core.database import init_db,close_db,create_table
from app.core.agent_graph import init_pg_saver,close_pg_saver
from fastapi import FastAPI

#
logger = logging.getLogger(__name__)

#统一管理数据库，redis生命周期
@asynccontextmanager
async def app_lifespan(app:FastAPI):
    """
     应用生命周期：
      yield 前 → 顺序初始化 PostgreSQL、Redis、langgraph的检查点
      yield 后 → 逆序关闭 langgraph的检查点、Redis、PostgreSQL
    :param app:FastAPI实例
    :return:
    """
    #先启动PG
    logger.info("应用启动中")
    try:
        await init_db(app)

    except Exception as e:
        logger.critical(f"PostgreSQL 初始化失败，应用拒绝启动：{e}")
        raise

    #启动redis
    try:
        await init_redis(app)

    except Exception as e:
        await close_db(app) #运行到这里说明PG已经初始化，得回滚
        logger.critical(f"Redis 初始化失败，应用拒绝启动：{e}")
        raise

    logger.info("所有服务就绪，开始接收请求")
    #启动检查点
    try:
        await init_pg_saver(app)
    except Exception as e:
        await close_db(app)
        await close_redis(app)
        logger.critical(f"langgraph检查点初始化失败，应用拒绝启动：{e}")
        raise

    #建表
    try:
        await create_table(app)

    except Exception as e:
        await close_redis(app)
        await close_db(app)
        await close_pg_saver(app)
        logger.critical(f"建表失败{e}")
        raise

    yield #上面的代码启动时会运行

    logger.info(" 应用关闭中...")
    await close_pg_saver(app) #最后初始化的先关：langgraph 检查点
    await close_redis(app)    #Redis
    await close_db(app)       #PostgreSQL
    logger.info("所有服务已安全关闭")



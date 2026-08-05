"""
创建PG连接池（打通PG和python之间的屏障）
"""
import logging
from sqlmodel import SQLModel
from fastapi import FastAPI, Request
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from app.core.config import settings

#配置日志
logger = logging.getLogger(__name__)

#
async def init_db(app:FastAPI):
    """
    启动时：创建 engine + async_sessionmaker()，挂到 app.state
    :param app: FastAPI实例对象
    :return:
    """
    logger.info("正在初始化 PostgreSQL 引擎...")

    # 创建连接池
    engine = create_async_engine(
        settings.pg_url,
        pool_pre_ping=True,  # 测试连接是否活跃
        pool_size=10,
        max_overflow=20,
        pool_timeout=30,
        pool_recycle=360
    )

    # 创建会话工厂类
    async_session = async_sessionmaker(
        bind=engine,
        expire_on_commit=False,
    )

    #挂载到app.state供get_session()依赖注入使用
    app.state.db_engine = engine
    app.state.async_session = async_session

async def close_db(app:FastAPI):
    """
    关闭时：销毁 engine（释放连接池）
    :param app: FastAPI实例对象
    :return:
    """
    engine = getattr(app.state,"db_engine",None)
    if engine:
        await engine.dispose()
        logger.info("PostgreSQL 引擎已销毁")

async def get_session(request:Request)->AsyncSession:
    """
    依赖注入：每次请求获取一个数据库会话。
    :param request:
    :return:
    """
    async_session : async_sessionmaker = request.app.state.async_session
    async with async_session() as session:
        yield session

#建表函数
async def create_table(app:FastAPI):
    async with app.state.db_engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)










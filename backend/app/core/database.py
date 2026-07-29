"""
创建PG连接池（打通PG和python之间的屏障）
"""
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from app.core.config import settings


#创建连接池
engine = create_async_engine(
    settings.pg_url,
    pool_pre_ping=True, #测试连接是否活跃
    pool_size=10,
    max_overflow=20,
    pool_timeout=30,
    pool_recycle=360
)

#创建会话工厂类
async_session = async_sessionmaker(
    bind=engine,
    expire_on_commit=False,
)

#生成对话
async def get_session() -> AsyncSession:
    async with async_session() as session:
        yield session
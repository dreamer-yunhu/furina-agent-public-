"""
创建PG连接池（打通PG和python之间的屏障）
"""
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from app.core.config import settings


engine = create_async_engine(settings.pg_url,echo=False)
AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
# FastAPI 每次请求进来，就从连接池拿一个“会话” (独立访问冰箱的通道)
async def get_db():
    async with AsyncSessionLocal() as session:
        yield session

"""
创建PG连接池（打通PG和python之间的屏障）
"""
import logging
from sqlmodel import SQLModel
from fastapi import FastAPI, Request
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
# ⚠️ AI 改动：settings 从 `furina_core.config` 改为 `furina_web.config` ——
#    pg_url 是 web 专属字段，已从 core 搬走（理由见 furina_web/config.py）。
from furina_web.config import settings

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
    # ⚠️ AI 改动：用 `settings.require_pg_url()` 而不是 `settings.pg_url`。
    #    区别：前者缺失时给**可操作的错误**，后者会把 None 传给 SQLAlchemy，
    #    报一个看不出原因的错（"NoneType is not a valid URL"）。
    engine = create_async_engine(
        settings.require_pg_url(),
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

#建表函数
async def create_table(app:FastAPI):
    """建表。

    ⚠️⚠️ AI 改动（**修一个静默陷阱**）：原来是无参的
            `SQLModel.metadata.create_all`
        它建的是"**所有已注册到 metadata 的表**"。

        而重构把表模型拆到了两个包：
            furina_core.models          → User / AgentThreadID
            furina_web.models.table     → Conversation / Message

        于是 web 启动时到底建出哪几张表，取决于"哪些模块恰好被 import 过"
        —— **不报错，只是少建表**，然后在第一次查询时抛
        `relation "xxx" does not exist`，而现场离得很远。

        改法：**显式列出本 app 要建的表**。web 需要全部四张
        （User 给认证用；AgentThreadID 给 /agent/threads 用；
          Conversation / Message 给对话用）。
    """
    # 这些 import 放在函数内：避免模块级 import 时就把所有表模型拉进来，
    # 让"哪张表属于谁"更显眼。
    from furina_core.models import AgentThreadID, User
    from furina_web.models.table import Conversation, Message

    tables = [
        User.__table__,
        AgentThreadID.__table__,
        Conversation.__table__,
        Message.__table__,
    ]
    async with app.state.db_engine.begin() as conn:
        await conn.run_sync(lambda sync_conn: SQLModel.metadata.create_all(sync_conn, tables=tables))
    logger.info("已确保 %d 张表存在：%s", len(tables), [t.name for t in tables])










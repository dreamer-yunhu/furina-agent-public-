"""
构建agent的图和定义初始化和关闭函数，方便管理生命周期
"""
from fastapi import FastAPI,Request
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg.rows import dict_row
from app.agent.graph import build_graph
from app.core.config import settings
from psycopg_pool import AsyncConnectionPool

#定义初始化检查点函数
async def init_pg_saver(app: FastAPI):
    #把连接池作为检查点
    dsn = settings.pg_url.replace("postgresql+asyncpg", "postgresql")
    pool = AsyncConnectionPool(
        conninfo=dsn,
        max_size=10,
        min_size=4,
        open=False,
        kwargs ={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row}
        #这几个参数作用："autocommit":True相当于即时存入，"row_factory": dict_row说明案列查询，兼容langgraph
    )
    app.state.pool = pool
    await pool.open()
    saver = AsyncPostgresSaver(pool)
    app.state.saver = saver
    await saver.setup()
    graph = build_graph(saver)
    app.state.graph = graph
#进程结束关闭检查点
async def close_pg_saver(app: FastAPI):
    await app.state.pool.close()

#获取编译后的图
async def get_graph(request: Request):
    """
    请求访问对应接时把图返还出来
    :param request: 请求
    :return: 编译完成的图
    """
    return request.app.state.graph

#获取检查点
async def get_saver(request: Request):
    """
    请求访问时把检查点对象返回
    :param request:
    :return:
    """
    return request.app.state.saver






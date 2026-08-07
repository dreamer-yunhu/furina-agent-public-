from fastapi import FastAPI
from app.core.lifespan import app_lifespan
from app.routers import auth, user, chat, knowledge, asset, ws
import logging



#定义FastAPI实例
app = FastAPI(title = "芙宁娜agent",lifespan=app_lifespan)
#挂载各业务领域子路由
app.include_router(auth.router)      # 认证
app.include_router(user.router)      # 用户
app.include_router(chat.router)      # 聊天
app.include_router(knowledge.router) # 知识库（预留）
app.include_router(asset.router)     # 资源（预留）
app.include_router(ws.router)        # WebSocket（预留）



#定义测试接口
@app.get("/")
async def root():
    return {"Hello":"World"}

#配置日志
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    filename='furina.log',
    filemode='a', #追加写入，不会覆盖原有内容
    encoding='utf-8'
)


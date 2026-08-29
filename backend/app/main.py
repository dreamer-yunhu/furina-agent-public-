from fastapi import FastAPI,Request,status
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse

from app.core.lifespan import app_lifespan
from app.routers import auth, user, chat, knowledge, asset, ws
import logging



#定义FastAPI实例
app = FastAPI(title = "芙宁娜agent",lifespan=app_lifespan)

# 大黑塔手笔: 演示用前端是直接打开 html 文件（file://），必须开 CORS 才能跨域调 API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],       # 演示环境全放开；生产环境务必收紧成具体域名
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
#挂载各业务领域子路由
app.include_router(auth.router)      # 认证
app.include_router(user.router)      # 用户
app.include_router(chat.router)      # 聊天
app.include_router(knowledge.router) # 知识库（预留）
app.include_router(asset.router)     # 资源（预留）
app.include_router(ws.router)        # WebSocket（预留）


logger = logging.getLogger(__name__) #兜底各种突发异常的日志

#定义测试接口
@app.get("/")
async def root():
    return {"Hello":"World"}
@app.exception_handler(Exception)
async def exception_handler(request: Request, exc: Exception):
    logger.error("未处理异常", exc_info=exc)   # traceback 记全
    return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,content={"detail": "服务器开小差了"})


#配置日志
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    filename='furina.log',
    filemode='a', #追加写入，不会覆盖原有内容
    encoding='utf-8'
)


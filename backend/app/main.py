from fastapi import FastAPI
from app.core.lifespan import app_lifespan
from app.routers import router as rt
import logging



#定义FastAPI实例
app = FastAPI(title = "芙宁娜agent",lifespan=app_lifespan)
app.include_router(rt.router) #挂载路由



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


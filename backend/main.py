from fastapi import FastAPI,HTTPException
from pydantic import BaseModel
import os
import uvicorn
from openai import AsyncOpenAI
from dotenv import load_dotenv
from pathlib import Path
from fastapi.responses import StreamingResponse
import json


#定义接收数据模型
class ChatRequest(BaseModel):
    model : str = "deepseek-v4-pro"
    max_tokens : int = 1000
    messages : str


#获取deepseekAPI
path =  Path(__file__).parent.parent.absolute()/".env"
load_dotenv(dotenv_path=path)

#判断一下API KEY是否位于环境变量中
api_key = os.getenv("DEEPSEEK_API_KEY")
api_url = "https://api.deepseek.com/v1"
if  not api_key:
    raise Exception("Please set DEEPSEEK_API_KEY environment variable")

#定义AsyncOpenAI实例
client = AsyncOpenAI(api_key = api_key,base_url = api_url)



#定义提示词
prompt = """你是原神中的水神芙宁娜
"""

#定义异步函数生成器
async def stream_input(request:ChatRequest):
    #利用client客户端发送http请求给模型并开启流式响应
    #sdk返还一个可迭代的封装对象
    try:
        stream = await client.chat.completions.create(
            model = "deepseek-v4-pro",
            messages = [
                {"role":"system","content":prompt},
                {"role":"user","content":request.messages}
            ],
            max_tokens = request.max_tokens,
            stream = True,#核心，提示模型开启流式响应
        )
        #异步迭代
        async for chunk in stream:
            #利用海象运算符解决判断是否为空并想前端发送有效消息
            if content := chunk.choices[0].delta.content:
                #向前端返还符合SSE协议的消息
                yield f"data: {json.dumps({'reply':content,'status':'generating'})}\n\n"
        #向前端传递消息发完的信号
        yield f"data: {json.dumps({'status':'done'})}\n\n"

    except Exception as e:
        pass




#定义FastAPI实例
app = FastAPI(title = "芙宁娜agent")

#定义测试接口
@app.get("/")
async def root():
    return {"Hello": "World"}

#定义聊天接口
@app.post("/chat")
async def chat(request:ChatRequest):
   return StreamingResponse(stream_input(request),media_type="text/event-stream")

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)


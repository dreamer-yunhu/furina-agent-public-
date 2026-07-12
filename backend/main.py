from fastapi import FastAPI,HTTPException
from pydantic import BaseModel
import os
import uvicorn
from openai import AsyncOpenAI
from openai import (AuthenticationError,RateLimitError,BadRequestError,APIConnectionError,APITimeoutError,
InternalServerError,APIError )
from dotenv import load_dotenv
from pathlib import Path
from fastapi.responses import StreamingResponse
import json


#定义接收数据模型
class ChatRequest(BaseModel):
    model : str = "deepseek-v4-pro"
    max_tokens : int = 1000
    user_input : str


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
            model = request.model,
            messages = [
                {"role":"system","content":prompt},
                {"role":"user","content":request.user_input}
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

    #进行异常捕获，注意，异常捕获的时候，从具体到抽象
    except AuthenticationError:
        #该异常用于捕获API密钥错误（可能是密钥失效，格式不对等等）
        yield f"data: {json.dumps({'error':'API 密钥无效，请检查服务器配置', 'code': 'AUTH_ERROR'})}\n\n"

    except RateLimitError:
        #该异常用于捕获请求次数异常
        yield f"data: {json.dumps({'error':'请求太繁忙，请稍后再试','code':'RATE_LIMIT'})}\n\n"

    except BadRequestError as e:
        #该异常用于捕获请求体中出现的异常
        error_msg = f'请求错误{e}'
        yield f"data: {json.dumps({'error':error_msg,'code':'BAD_REQUEST'})}\n\n"

    except APITimeoutError:
        #该异常用于捕获请求超时异常
        yield f"data: {json.dumps({'error':' 模型响应超时，请简化问题或稍后重试','code':'TIMEOUT'})}\n\n"

    except APIConnectionError:
        #该异常用于无法有效链接大模型api的异常
        yield f"data: {json.dumps({'error':'无法连接到模型服务，请稍后重试','code':'CONNECTION_ERROR'})}\n\n"

    except InternalServerError:
        #捕获服务器内发送的一些异常
        yield f"data: {json.dumps({'error':'模型服务内部错误','code':'SERVER_ERROR'})}\n\n"

    except APIError as e:
        #之前所有异常的父类，用于捕获其他未列出的 API 错误
        yield f"data: {json.dumps({'error':f'调用失败{e}','code':'API_ERROR'})}\n\n"

    except Exception as e:
        #大类异常兜底
        yield f"data: {json.dumps({'error':f'未知错误{e}','code':'UNKNOWN'})}\n\n"







#定义FastAPI实例
app = FastAPI(title = "芙宁娜agent")

#定义测试接口
@app.get("/")
async def root():
    return {"Hello":"World"}

#定义聊天接口
@app.post("/chat")
async def chat(request:ChatRequest):
   return StreamingResponse(stream_input(request),media_type="text/event-stream")

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)


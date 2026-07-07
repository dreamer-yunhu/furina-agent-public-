from fastapi import FastAPI,HTTPException
from pydantic import BaseModel
import os
import uvicorn
import httpx
from dotenv import load_dotenv
from pathlib import Path
from fastapi.responses import StreamingResponse
import json


#定义接收数据模型
class ChatRequest(BaseModel):
    model : str = "deepseek-v4-pro"
    max_tokens : int = 1000
    messages : str

#定义返还前端数据模型
class ChatResponse(BaseModel):
    text : str
    status : str

#获取deepseekAPI
path =  Path(__file__).parent.parent.absolute()/".env"
load_dotenv(dotenv_path=path)

#判断一下API KEY是否位于环境变量中
api_key = os.getenv("DEEPSEEK_API_KEY")
api_url = "https://api.deepseek.com/chat/completions"
if  not api_key:
    raise Exception("Please set DEEPSEEK_API_KEY environment variable")

#定义提示词
prompt = """你是原神中的水神芙宁娜
"""

#定义FastAPI实例
app = FastAPI(title = "芙宁娜agent")

#定义测试接口
@app.get("/")
async def root():
    return {"Hello": "World"}

#定义聊天接口
@app.post("/chat")
async def chat_stream(request:ChatRequest):
    #构造合法数据格式
    messages = [
        {"role":"system","content":prompt},
        {"role":"user","content":request.messages}
    ]
    #构造请求体
    payload = {
        "messages":messages,
        "model":request.model,
        "max_tokens":request.max_tokens,
        "stream": True #告诉deepseek开启流式响应
    }

    #构造请求头
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    #定义一个异步函数生成器
    async def generator():
        # 发送http请求
        async with httpx.AsyncClient(timeout=30) as client:
            try:
                # 发送请求，此时 DeepSeek 会开始源源不断地返回数据块
                async with client.stream("POST", api_url, json=payload, headers=headers) as response:
                    # 校验是否正常
                    response.raise_for_status()
                    #逐行读取deepseek返回的数据
                    async for line in response.aiter_lines():
                        #deepseek返回的数据格式是 SSE，每行以 "data: " 开头
                        if line.startswith("data: "):
                            json_str = line[6:]
                            # 如果收到 "[DONE]"，说明 AI 说完了
                            if json_str.strip() == "[DONE]":
                                break
                            try:
                                chunk = json.loads(json_str)
                                # 提取增量文本
                                delta = chunk["choices"][0].get("delta", {})
                                content = delta.get("content", "")

                                # 【核心】只要有一点点内容，就立刻发给前端
                                if content:
                                    yield content

                            except json.JSONDecodeError:
                                continue  #忽略解析错误的行
            except Exception as e:
                yield f"\n\n[Error]: {str(e)}"

    # 3. 将生成器包装成 StreamingResponse 返回
    # media_type="text/event-stream" 是 SSE (Server-Sent Events) 的标准格式
    return StreamingResponse(generator(), media_type="text/event-stream")



if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1")


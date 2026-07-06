from fastapi import FastAPI,HTTPException
from pydantic import BaseModel
import os
import uvicorn
import httpx
from dotenv import load_dotenv
from pathlib import Path

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
api_key = os.getenv("DEEPSEEK_API_KEY").strip()
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
async def chat(request:ChatRequest):
    #构造合法数据格式
    messages = [
        {"role":"system","content":prompt},
        {"role":"user","content":request.messages}
    ]
    #构造请求体
    payload = {
        "messages":messages,
        "model":request.model,
        "max_tokens":request.max_tokens
    }

    #构造请求头
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    #发送http请求
    async with httpx.AsyncClient(timeout=30) as client:
        try:
            response = await client.post(api_url, json=payload,headers=headers,timeout=30)
            response.raise_for_status() #检查返还的HTTP状态码，不是200报错
            result = response.json()  #将返还结果转为python字典
            furina_reply = result["choices"][0]["message"]["content"]
            return ChatResponse(text=furina_reply, status="success")


        except httpx.HTTPStatusError as e:
            #捕获401，402之类的异常
            raise HTTPException(status_code=e.response.status_code, detail=f"DeepSeek API 错误: {e.response.text}")

        except Exception as e:
            #大类异常兜底
            raise HTTPException(status_code=500, detail=f"内部服务器错误: {str(e)}")

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1")


import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import os
import json
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv
import urllib.request
import urllib.error
import chromadb

# ===== 加载 .env =====
env_path = Path(__file__).resolve().parent.parent / '.env'
load_dotenv(dotenv_path=env_path)

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY").strip()
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL").strip()
# 上述代码作用：加载环境变量，获取 DeepSeek API 密钥与地址

# ===== FastAPI 初始化 =====
app = FastAPI(title="Furina Agent")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# 上述代码作用：创建 FastAPI 应用并配置跨域，允许前端调用

# ===== 芙宁娜人设 =====
SYSTEM_PROMPT = """你是芙宁娜，原神中的水神，众水、众方、众民与律法的女王。
你优雅、聪慧，带一点戏剧化的浮夸，但内心温柔。
当检索到与你问题高度相关的语音台词时，请直接引用原文，并加上动作描写，不要自己编造。
回答时保持水神的端庄，偶尔俏皮，回复长度控制在100字以内。"""
# 上述代码作用：定义芙宁娜的系统人物设定，注入每次对话

# ===== 请求体模型 =====
class ChatRequest(BaseModel):
    message: str
# 上述代码作用：声明聊天请求的 JSON 格式，只包含 message 字段

# ===== 初始化 ChromaDB 语音知识库（只连接一次） =====
db_path = Path(__file__).parent.parent / "chroma_db"
chroma_client = chromadb.PersistentClient(path=str(db_path))
voice_collection = chroma_client.get_or_create_collection("furina_voice")
# 上述代码作用：启动时连接 ChromaDB 并获取（或创建）芙宁娜语音向量集合，后续复用

def search_voice(query: str, top_k: int = 3) -> list:
    """从芙宁娜语音库中检索匹配的台词"""
    results = voice_collection.query(query_texts=[query], n_results=top_k)
    docs = results["documents"][0] if results["documents"] else []
    return docs
# 上述代码作用：基于用户输入从语音向量库中检索最相关的芙宁娜台词，返回字符串列表

@app.get("/")
def root():
    return {"message": "芙宁娜已就绪，我的子民。"}
# 上述代码作用：根路径健康检查，确认服务运行

@app.post("/chat")
def chat(request: ChatRequest):
    user_raw = request.message

    # 1. 检索语音台词作为上下文
    voice_hits = search_voice(user_raw)
    voice_context = "\n".join(voice_hits) if voice_hits else ""

    # 2. 构建增强的用户消息
    if voice_context:
        enhanced_message = (
            f"[芙宁娜的语音台词参考]\n{voice_context}\n\n"
            f"[子民的留言]\n{user_raw}"
        )
    else:
        enhanced_message = user_raw

    try:
        # 3. 组装请求发给 DeepSeek
        url = f"{DEEPSEEK_BASE_URL}/v1/chat/completions"
        data = {
            "model": "deepseek-v4-pro",
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": enhanced_message}
            ],
            "temperature": 0.8,
            "max_tokens": 500
        }
        json_data = json.dumps(data).encode('utf-8')

        headers = {
            "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
            "Content-Type": "application/json"
        }

        req = urllib.request.Request(url, data=json_data, headers=headers, method='POST')
        with urllib.request.urlopen(req, timeout=30) as response:
            resp_body = response.read().decode('utf-8')
            resp_data = json.loads(resp_body)

        reply = resp_data["choices"][0]["message"]["content"]
        return {"reply": reply}
        # 上述代码作用：发送 HTTP 请求到 DeepSeek API，获取并返回芙宁娜的回复

    except urllib.error.HTTPError as e:
        error_body = e.read().decode('utf-8')
        print(f"[DeepSeek HTTP错误] {e.code}: {error_body}")
        raise HTTPException(status_code=500, detail=f"DeepSeek API错误 {e.code}: {error_body}")
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
    # 上述代码作用：统一捕获异常，打印详细错误并返回 500 状态码

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8765)
# 上述代码作用：当直接运行脚本时启动 Uvicorn 服务器
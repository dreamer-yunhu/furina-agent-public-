"""
将大模型API key注入环境变量中并配置客户端（客户端是建立大模型与我的脚本的桥梁）
"""
import os
from dotenv import load_dotenv
from pathlib import Path
from openai import AsyncOpenAI

#加载.env文件中的API key
path = Path(__file__).parent.parent.parent.parent.resolve() /".env"
#注入环境变量
load_dotenv(dotenv_path=path)
API_KEY = os.getenv("DEEPSEEK_API_KEY")
BASE_URL = "https://api.deepseek.com/v1"
#配置客户端
deepseek_client = AsyncOpenAI(api_key=API_KEY, base_url=BASE_URL)

#检测是否成功注入
if not API_KEY:
    raise ValueError("API_KEY not set")

#配置相关信息
class Settings:
    def __init__(self):
        self.pg_url = os.getenv("PG_URL")
        self.redis_url = os.getenv("REDIS_URL")
        self.jwt_key = os.getenv("JWT_SECRET_KET")
        self.jwt_algo = os.getenv("JWT_ALGO")
        self.access_token_expire_seconds= 3600
        self.refresh_token_expire_days = 30
settings = Settings()


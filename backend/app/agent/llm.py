"""
初始化llm
"""
from app.core.config import settings
from langchain_openai import ChatOpenAI
llm = ChatOpenAI(
    model="deepseek-v4-flash",
    base_url=settings.base_url,
    api_key=settings.api_key,
)
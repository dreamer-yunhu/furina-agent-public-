"""
放置agent的公共工具
"""
import httpx
from langgraph.prebuilt import ToolNode
from furina_core.config import settings
from langchain.tools import tool
#全局唯一HTTP工具客户端
async def get_http_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=httpx.Timeout(15.0, connect=5.0),
        limits=httpx.Limits(max_keepalive_connections=5, max_connections=20),
        headers={"furina": "web_search"}
    )


#写调用博查的工具
@tool
async def bocha_search_tool(query):
    """
        使用博查Web Search API进行网页搜索，返回摘要信息。
        :param query: 查询关键字
        :return:查询结果
        """
    client = await get_http_client()
    response = await client.post(
        url="https://api.bocha.cn/v1/web-search",
        headers={"Authorization": f"Bearer {settings.search_api_key}","Content-Type": "application/json"},
        json={"query": query, "count": 5}
    )
    return response.json()



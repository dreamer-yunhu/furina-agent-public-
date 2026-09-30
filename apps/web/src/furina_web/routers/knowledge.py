"""
知识库路由：RAG 检索调试/预览（预留）
"""
from fastapi import APIRouter

router = APIRouter(prefix="/knowledge", tags=["知识库"])

# TODO: 接入 ChromaDB 检索（persona / voice / world-knowledge）
# @router.get("/search")
# async def search(q: str):
#     ...

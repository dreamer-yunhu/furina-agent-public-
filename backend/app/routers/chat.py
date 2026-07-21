"""
定义聊天接口的文件
"""
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from app.schemas.model import ChatRequest
from app.services.stream import stream_chat

router = APIRouter() #定义路由层
@router.post("/chat")
async def chat(request:ChatRequest):
    return  StreamingResponse(stream_chat(request),media_type="text/event-stream")
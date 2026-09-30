"""
WebSocket 路由：Unity 客户端双向指令通道（预留）
"""
from fastapi import APIRouter, WebSocket

router = APIRouter(tags=["WebSocket"])


@router.websocket("/ws/unity")
async def unity_ws(websocket: WebSocket):
    """最小回声原型，后续替换为：指令下发 + ack 确认 + 状态上报"""
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_text()
            await websocket.send_text(data)
    except Exception:
        await websocket.close()

"""
资源路由：图片、语音等产物访问（ComfyUI 出图 / TTS 音频，预留）
"""
from fastapi import APIRouter

router = APIRouter(prefix="/assets", tags=["资源"])

# TODO: 挂载静态产物目录
# app.mount("/assets", StaticFiles(directory=...), name="assets")

"""
路由包：各业务领域的子路由模块在此导出，main.py 逐个挂载
"""
from app.routers import auth, user, chat, knowledge, asset, ws

__all__ = ["auth", "user", "chat", "knowledge", "asset", "ws"]

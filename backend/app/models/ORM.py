from sqlalchemy import Column, Integer, String, Text, DateTime, func,Index
from sqlalchemy.orm import declarative_base

#这是所有表的“基类”
Base = declarative_base()
class ChatMessage(Base):
    __tablename__ = "chat_message" #告诉 SQLAlchemy，这个类对应数据库里名叫 chat_messages的表（命名操作）
    id = Column(Integer, primary_key = True,autoincrement=True) #显式声明自主增键，提高兼容性。自动编号
    session_id  = Column(String(64),index=True) #存储出自哪个窗口
    role = Column(String(16))# 存储"role"或"assistant"
    content = Column(Text)#存储对话文本
    created_at = Column(DateTime(timezone=True),server_default=func.now()) #创建时间戳（记录时间）
    #加入联合索引
    __table_args__ = (
        Index("ix_chat_session_created", "session_id", "created_at"),
    )
    #调试代码
    def __repr__(self):
        return f"<{self.role}>{self.content[:20]}..."

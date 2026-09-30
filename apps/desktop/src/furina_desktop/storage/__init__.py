"""桌面端的存储层。

    local_store.py   SQLite —— agent 状态（LangGraph checkpoint）

两者都实现 `furina_core` 里的协议，所以业务代码只依赖协议：

    CheckpointStore  (furina_core.checkpoint)  ←  web 用 PG 实现，desktop 用 SQLite 实现
"""

# ── AI-ASSISTED ── 本文件由 AI 生成/改写，待人工复核 ──
# 复核重点：纯导出。LanceDB（向量）的实现在 M2 才加，届时放本目录下的 vector_store.py。

from furina_desktop.storage.local_store import SqliteCheckpointStore

__all__ = ["SqliteCheckpointStore"]

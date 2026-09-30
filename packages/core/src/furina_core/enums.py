"""跨产品共享的枚举 —— 最小、无依赖。

从原 `backend/app/schemas/model.py` 里**只拆出 MessageRole**，理由是一个**依赖方向问题**：

    原来：`models/table.py` → `from app.schemas.model import MessageRole`
    问题：**表模型依赖了契约模块**。而按新分区，表模型在 web（甚至 core），
          契约也在 web —— 看似没事，但 `Message.role` 这个列**两边都要用**，
          一旦 desktop 也要存消息（它现在存的是 checkpoint，将来可能有本地历史），
          这个枚举就必须在共享层。

    所以：`MessageRole` 是**共享原语**，不是 web 的契约。放在这里。

⚠️ 本模块**刻意不 import 任何东西**（除了 stdlib 的 enum）。
   它是依赖图的叶子节点 —— 谁都依赖它，它不依赖谁。
"""

# ── AI-ASSISTED ── 本文件由 AI 生成/改写，待人工复核 ──
# 复核重点：从 schemas/model.py 拆出来的，**只搬了 MessageRole 这一个类**。
# 原来的文件头注释"用于定义数据模型"和"定义openai SDK接收数据模型"已按实际含义重写。

from enum import Enum


class MessageRole(str, Enum):
    """消息角色。

    继承 `str` 而不是 `StrEnum`：这样 `json.dumps` 能直接序列化成员，
    而普通 `Enum` 会 TypeError（原实现在 docs/NOTES.md 里记过这个坑）。
    """

    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"

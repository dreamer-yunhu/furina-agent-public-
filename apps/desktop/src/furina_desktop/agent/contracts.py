"""agent 的图状态契约 —— 审批（HITL）相关类型。

为什么这些**不叫** API 契约：
    它们是 `interrupt()` 抛出的载荷与 `Command(resume=)` 收回的载荷，
    是**图的内部状态类型**。HTTP 只是它们的运输方式之一。
    放在 `api/contracts.py` 会让 `agent/` 反向依赖 `api/`。

    `AgentRequest` / `ThreadCreate` / `RenameThread` 才是真正的 HTTP 请求体，
    它们在 `furina_desktop.api.contracts`。
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class ReviewAction(str, Enum):
    """审批动作。

    ⚠️ 这里我从 `StrEnum` 改成了 `str, Enum`，**这是有意的**：
    `interrupt()` 的载荷要 JSON 可序列化，而 `str, Enum` 的成员
    同时也是 str，`json.dumps` 直接能处理（docs/NOTES.md 记过这个区别）。
    两种写法都能满足这个要求，`str, Enum` 的兼容面更宽。
    """

    APPROVE = "approve"
    REJECT = "reject"


# 规定工具分级字段
class ToolRisk(str, Enum):
    """工具风险分级。

    ⚠️ 现状：**这个枚举全项目无人使用**（见 docs/NOTES.md 记账）。
    风险分级目前靠 `agent/registry.py` 里的 SAFE_TOOLS / RISKY_TOOLS 硬编码名单。
    保留它是为了将来"加工具时忘登记"能被 fail-closed 挡住。
    """

    SAFE = "safe"  # 不送审
    RISKY = "risky"  # 送审
    UNKNOWN = "unknown"  # 不送审，直接挡下（fail-closed）


# 规定审核载荷
class WritePreview(BaseModel):
    """送审的单个写操作预览。"""

    tool_call_id: str  # 工具调用id
    # ── T23：数据库审批行 id；旧 checkpoint 兼容为 None ──
    approval_id: str | None = None
    path: str  # 沙箱相对，不给绝对路径
    # ── AI 新增（T34）──
    # 写工具现在会自动建父目录，但"会建哪些"必须让审批人看见，
    # 否则他批准的是"写一个文件"，实际执行的是"建目录 + 写文件"。
    # 顺序：由浅到深（如 ["sub", "sub/dir"]）；父目录都已存在时为空列表。
    creates_dirs: list[str] = Field(default_factory=list)
    is_new_file: bool
    old_hash: str | None  # 新建时为 None，乐观锁——保证文件是提出审核时的内容，如果用户在审核期间改了重审
    added: int
    removed: int
    diff: str


# 定义interrupt()发送载荷
class ReviewRequest(BaseModel):  # interrupt() 抛出侧
    type: Literal["review_request"] = "review_request"
    action: Literal["review_request"] = "review_request"
    requests: list[WritePreview]  # 请求是列表，那么审批也得是逐个审批


# 定义Command()接收载荷
class ItemDecision(BaseModel):
    """对单个 `WritePreview` 的裁决。"""

    tool_call_id: str  # 关联回 WritePreview
    # ── T23：决定回指数据库行；T23-3 才强制要求 ──
    approval_id: str | None = None
    action: ReviewAction
    # <- AI 改动：补默认值 None。
    #    Pydantic v2 里 `str | None` 不带默认值仍然是**必填**，前端批准时通常
    #    不会带 reason，结果整个 /agent/resume 请求在进入 handler 前就 422
    #    （冒烟实测：缺省 body 直接 422，连线程归属都来不及校验）。
    #    复核重点：语义上 reason 只在拒绝时有意义，批准可省略。
    reason: str | None = None


# 前端发的是审核工具的集合
class ReviewDecision(BaseModel):  # Command(resume=) 收回侧
    type: Literal["review_decision"] = "review_decision"
    decisions: list[ItemDecision]  # 实现逐个审批

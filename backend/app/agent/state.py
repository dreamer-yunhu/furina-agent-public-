"""
用于定义在各个节点间流转的状态模型

⚠️ 2026-09-11 重构：messages 单字段 → 强类型领域状态（PLAN §十四）

✅ state schema 用 Pydantic BaseModel（已拍板，2026-09-11）
   - 保留属性访问 `state.xxx`，且自带运行时校验
   - 代价：官方文档/教程示例多为 TypedDict，抄例子时要翻译
   - TypedDict 的 NotRequired 在这里用 Optional[T] / Field(default=...) 代替
"""
from typing import Annotated, Literal
from pydantic import BaseModel, Field

from langgraph.graph.message import add_messages

from app.schemas.model import ReviewRequest


class SupervisorState(BaseModel):
    """主图状态

    设计原则：只放"跨节点流转"的东西。节点内部的临时变量不要进 state。
    """

    messages: Annotated[list, add_messages]
    """对话历史。add_messages reducer 负责按 id 合并/覆盖"""

    mode: Literal["roleplay", "code"]
    """双模式开关（PLAN §七）：闲聊注入全人设，代码场景收敛人设保准确性"""

    user_name:str|None = Field(default=None,max_length=255)

    personal_preference:str|None = Field(default=None,max_length=255)

    rag_result: str | None = Field(default=None)

    subagent_task: str | None = Field(default=None)
    # TODO: [状态-1] 用户画像位
    #   提示：§七 的「用户画像注入」节点往这里写 user_name / personal_preference
    #   边界：首次进入图时这个字段可能不存在 → TypedDict 下缺失 key 会 KeyError
    #        用 NotRequired 标注，还是让它必填由入口保证？

    # TODO: [状态-2] 检索结果位
    #   提示：RAG 检索节点的产物，供 LLM 生成节点消费
    #   边界：不检索时这个字段应该是什么？空列表 vs 不写入

    # TODO: [状态-3] 意图路由位
    #   提示：意图路由节点的判断结果，条件边读它决定走哪条路
    #   边界：路由用规则优先还是 LLM 兜底（PLAN §七 原定"规则优先，LLM 兜底"）

class CoderState(BaseModel):
    coder_messages: Annotated[list, add_messages]
    pending_reviews : ReviewRequest|None = Field(default=None) #表示当前是否有等待处理的审核——载荷快照
    decision_reviews:list|None = Field(default=None)

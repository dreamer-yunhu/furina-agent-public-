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



class SupervisorState(BaseModel):
    """主图状态

    设计原则：只放"跨节点流转"的东西。节点内部的临时变量不要进 state。
    """

    messages: Annotated[list, add_messages]
    """对话历史。add_messages reducer 负责按 id 合并/覆盖"""

    # ── Stage A（D-SUP-04）：`mode` 已删除，不要恢复 ──
    # 旧字段 `mode: Literal["roleplay","code"]` 是开发期占位，从来不是意图。
    # 现在的路由权威位是下面的 `intent`（模型产出 + 程序校验）。
    # ⚠️ Pydantic 默认忽略未知字段：外部若还在传 "mode"，会被**静默丢弃**，
    #    不会报错 —— 所以新增调用方时请对照本文件，而不是照抄旧代码。
    #    迁移记录见 docs/audit/2026-10-26-StageA-Phase0-核对报告.md §D-SUP-04

    # ── Stage A：主管输入（D-SUP-05）──
    task_input: str | None = Field(default=None)
    """用户本次请求的**唯一权威位**。子图拿到的 `subagent_task` 由它显式映射而来。"""

    # ── Stage A：意图路由（D-SUP-01 / D-SUP-02）──
    intent: Literal["CHAT", "CODE"] | None = Field(default=None)
    """**校验通过后**的意图。条件边只认它，且只能由 validate_intent_node 写入。"""

    intent_raw: str | None = Field(default=None)
    """模型的原始输出。单独存放，**不得写进 messages**（否则会被当成对话内容）。"""

    intent_error: str | None = Field(default=None)
    """上一次校验的失败原因；非空时说明正在重试，会回填给模型。"""

    intent_attempts: int = Field(default=0)
    """已调用意图模型的次数。上限见 supervisor.MAX_INTENT_ATTEMPTS。"""

    # ── Stage A：业务结果（D-SUP-06，与 T23 生命周期状态正交）──
    route_status: Literal["ok", "failed"] | None = Field(default=None)
    """`failed` 只表示"路由没走通"，不代表图没跑到 END。运行时据此判 Task=FAILED。"""

    route_error: str | None = Field(default=None)

    result: str | None = Field(default=None)
    """子图的业务结果（V1：CHAT 的回复文本、CODE 最终说明）。"""

    user_name:str|None = Field(default=None,max_length=255)

    personal_preference:str|None = Field(default=None,max_length=255)

    rag_result: str | None = Field(default=None)

    subagent_task: str | None = Field(default=None)

    # ── T23：运行时标识（由 /agent 创建后传入）──
    # 只放字符串，不放 ORM 对象；子图与父图同名，才能通过节点边界传进去。
    task_id: str | None = Field(default=None)
    execution_id: str | None = Field(default=None)

    # TODO: [状态-1] 用户画像位
    #   提示：§七 的「用户画像注入」节点往这里写 user_name / personal_preference
    #   边界：首次进入图时这个字段可能不存在 → TypedDict 下缺失 key 会 KeyError
    #        用 NotRequired 标注，还是让它必填由入口保证？

    # TODO: [状态-2] 检索结果位
    #   提示：RAG 检索节点的产物，供 LLM 生成节点消费
    #   边界：不检索时这个字段应该是什么？空列表 vs 不写入

    # [状态-3] 已落地：见上方 intent / intent_raw / intent_error / intent_attempts
    #   原定"规则优先，LLM 兜底"在 Stage A 改为"模型产出 + 程序校验"（D-SUP-01/02）

class CoderState(BaseModel):
    # <- AI 改动：补上 subagent_task。
    #    原因：prepare_node 一直在读它，但子图状态里没有这个字段，实测直接
    #    AttributeError（阶段 1 报告 B1）。父图的同名字段会通过 add_node 传进来。
    subagent_task: str | None = Field(default=None)
    # ── T23：审批必须绑定真实 Task/Execution ──
    task_id: str | None = Field(default=None)
    execution_id: str | None = Field(default=None)
    coder_messages: Annotated[list, add_messages] = Field(default_factory=list)
    # <- AI 改动：两个审批字段都改成 **纯 dict**。
    #    原因：LangGraph 落 checkpoint 时会对自定义类型告警
    #    "Deserializing unregistered type ... will be blocked in a future version"，
    #    实测已出现（ReviewRequest）。状态里只放 JSON 可序列化的数据，
    #    到节点边界再用 Pydantic 校验，既不会随 LangGraph 版本变化而坏，
    #    InMemory / SQLite / PG 三种 saver 的行为也一致。
    #    复核重点：dict 的形状校验现在由 execute_node 负责，别再偷偷塞别的类型。
    pending_reviews: dict | None = Field(default=None) #表示当前是否有等待处理的审核——载荷快照
    decision_reviews: dict | None = Field(default=None)
    # ── T23-4：本次获准执行的高风险批次（approval_id ↔ tool_call_id）──
    # 只放字符串/字典，不放 ORM；由 execute_node 写入，guarded_tools_node 消费后清空。
    approved_approvals: list[dict] | None = Field(default=None)
    # <- AI 改动（Stage A）：CODE 的输出契约位。
    #    与 SupervisorState 同名 → 子图结束时按字段映射回传给主管（D-SUP-05）。
    #    复核重点：只放**结论文本**，不要把 coder_messages 整个搬出去。
    result: str | None = Field(default=None)


class ChatState(BaseModel):
    """CHAT 子图状态（Stage A）。

    # <- AI 新增（Stage A）
    为什么单独一个 State 而不是复用 SupervisorState：
      · D-SUP-05 要求主管与子图使用**独立契约**，主管不需要知道 child 的内部消息；
      · D-SUP-08 要求"不得假设所有子图都有 coder_messages"——CHAT 用自己的字段；
      · 用独立字段名（chat_messages）才不会和主管的 messages 互相污染。

    复核重点：这里**没有** pending_reviews / coder_messages 等审批字段——
    CHAT 不挂工具、不需要审批，不要为了"统一"把它们补进来。
    """

    # 与主管共享的输入（靠同名映射传进来）
    task_input: str | None = Field(default=None)
    # 只有 CHAT 自己有
    chat_messages: Annotated[list, add_messages] = Field(default_factory=list)
    # 与主管共享的输出
    result: str | None = Field(default=None)

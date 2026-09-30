"""furina-desktop —— 桌面版后端（Tauri 壳的本地服务）。

职责边界：

    agent 编排      LangGraph 主管图 + coder 子图（手搓 StateGraph，非 create_agent）
    工具            read / write 文件工具，受 furina_core.sandbox.PathJail 约束
    HITL 审批       写操作送审 -> interrupt 冒泡 -> 人批准/拒绝 -> resume
    存储            SQLite（会话/线程元数据 + LangGraph checkpoint）
                    LanceDB（向量检索，供 RAG 用）
    限流            furina_core.limits.LocalTokenBucket（进程内，限出站 LLM 调用）

**刻意不包含**：多用户认证、Redis、邮件表单校验 —— 单用户本地应用没有这些语义。
「限流熔断保留」但实现换成进程内版本（桌面端没有 Redis）。

⚠️ 当前状态：本包只有骨架，源码正在从 backend/ 迁移过来。
"""

# ── AI-ASSISTED ── 本文件由 AI 生成/改写，待人工复核 ──
# 复核重点：纯文档占位（让 uv_build 找到模块）。
# 搬 agent 代码时有四个已知坑（都在 AI-CHANGES.md 里）：
#   1. `AsyncPostgresSaver` 要换掉 —— SQLite 是 LangGraph 官方支持的另一条路
#      还是自管状态，**这个决定没做，是最大的未知**
#   2. coder.py 里硬编码的 `C:/furina-agent/backend/app/prompt/coder.txt` 必须去掉
#   3. `decision_review` 与 `decision_reviews` 的拼写不一致（静默不共享）
#   4. `executor_node` 是空函数体且从未 add_node

__version__ = "0.1.0"

__all__ = ["__version__"]

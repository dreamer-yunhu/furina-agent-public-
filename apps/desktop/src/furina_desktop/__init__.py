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

⚠️ 当前状态：**本包是唯一现行实现**。旧单体 `backend/` 已于 2026-10-23 删除。
"""

# ── AI-ASSISTED ── 本文件由 AI 生成/改写，待人工复核 ──
# 复核重点：纯文档占位（让 uv_build 找到模块）。
# 旧单体迁移的四个已知坑均已在 2026-10-22 修复：
#   1. `AsyncPostgresSaver` → `SqliteCheckpointStore`（storage/local_store.py）
#   2. 提示词硬编码路径 → `agent/prompts/loader.py`
#   3. `decision_review` / `decision_reviews` 拼写 → 已统一
#   4. `execute_node` 空函数体 → 已实现并注册（nodes/coder.py）

__version__ = "0.1.0"

__all__ = ["__version__"]

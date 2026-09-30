"""furina-web —— Web 版后端，部署到域名。

职责边界（这是它和 desktop 的分工，别混）：

    多用户认证     注册 / 登录 / 双令牌 / Redis 黑名单 / 单会话顶号
    对话（闲聊）   角色扮演模式的流式对话 + 历史持久化
    存储           Postgres（业务表）+ Redis（热缓存 / 会话 / 黑名单）
    RAG            人设与世界观语料检索（复用 knowledge/，见后续模块）

**刻意不包含**：agent 编排、工具调用、HITL 审批、文件沙箱 —— 那些是 desktop 的。
依赖上也不含 langgraph / langchain / psycopg，见 pyproject.toml。

⚠️ 当前状态：本包只有骨架，源码正在从 backend/ 迁移过来。
"""

# ── AI-ASSISTED ── 本文件由 AI 生成/改写，待人工复核 ──
# 复核重点：这个 __init__.py 是纯文档占位（为了让 uv_build 找到模块）。
# 真正的内容要等 backend/ 的 chat/auth/user 那一半搬进来。
# 搬的时候注意三件事（见 AI-CHANGES.md）：
#   1. `app.*` 的包名要全改成 `furina_web.*`
#   2. MessageRole 要从 schemas/model.py 提到 furina_core（否则 models 反向依赖 schemas）
#   3. create_all 要换成显式表清单（否则拆完会静默漏表）

__version__ = "0.1.0"

__all__ = ["__version__"]

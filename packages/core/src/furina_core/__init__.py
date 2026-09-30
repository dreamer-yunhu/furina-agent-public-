r"""furina-core —— web 与 desktop 共享的内核。

═══════════════════════════════════════════════════════════════════════
设计红线（比代码本身重要）
═══════════════════════════════════════════════════════════════════════

**红线一：不依赖任何具体存储后端。**
    core 里**不准**出现 `asyncpg` / `psycopg` / `redis` / `lancedb`。
    理由：web 用 PG + Redis，desktop 用 SQLite + LanceDB。
    一旦 core 引了其中任何一个，另一边就白背一个它不用的数据库驱动
    —— 那正是这次重构要消除的东西。

    ✅ 可机械检查：
        grep -E "^\s*(import|from) (asyncpg|psycopg|redis|lancedb)" packages/core/src

**红线二：core 不 import 具体的 app。**
    依赖方向永远是 `app -> core`，单向。

**红线三：包根零副作用。**
    本文件刻意不 import 任何子模块 —— 因为 desktop 只用 `furina_core.limits`，
    不该因为 `import furina_core` 就把 bcrypt 也拖进来。
    用法一律显式：`from furina_core.security import hash_password`

    ⚠️ **这份清单里"deliberately not"的语法保证来自 RED LINE ONE，不是 RED LINE THREE**
    （上面标注有误，保留原意，见文件末尾的"已知不一致"）。

═══════════════════════════════════════════════════════════════════════
⚠️ 一条已经修改的红线（2026 本次会话，务必读）
═══════════════════════════════════════════════════════════════════════

**我最初写的红线是"本包零框架依赖"**（不 import fastapi / sqlmodel / sqlalchemy / pydantic /
openai）。搬运完成后实测发现**这条红线不成立**：

    furina_core/models.py           → import sqlmodel（共享表模型：User / AgentThreadID）
    furina_core/storage/session.py  → import fastapi + sqlalchemy（共享的会话依赖）
    furina_core/config.py           → import openai（make_async_client）
    furina_core/enums.py            → import pydantic（契约枚举）

**为什么没有把它们赶出 core**：这四样**两边都要**。
    · 表模型：web 存 PG、desktop 存 SQLite，但**表结构是共享的**
    · 会话依赖：两边都用 SQLAlchemy 的 `AsyncSession` + FastAPI 的 `Depends`
    · LLM 客户端：两边都调同一个 OpenAI 兼容服务

**所以红线改了**：从"零框架"改成"**零存储后端**"（红线一）。
    "零框架"是个**当时未经验证的理想**，实测站不住 ——
    留着它比改掉它更危险（下一个读代码的人会以为它成立）。

**教训**：红线要能被机械检查。"不依赖框架"没法检查，"不出现 asyncpg/psycopg/redis/lancedb"
可以一条 grep 验完。

═══════════════════════════════════════════════════════════════════════
模块地图
═══════════════════════════════════════════════════════════════════════

    config            配置基类 + 全局 settings + LLM 客户端工厂
    enums             共享枚举（MessageRole）—— 依赖图的叶子节点
    errors            通用校验异常（幻觉工具/幻觉参数/缺参数）
    models            共享表模型（User / AgentThreadID）
    security          bcrypt + JWT 原语（不含会话与黑名单）
    circuit_breaker   三态熔断器（原 core/redis_fuse.py，已去 Redis 依赖）
    circuit_policies  fail-open / fail-closed 两种降级策略
    sandbox           路径越界守卫 PathJail
    checkpoint        ★ CheckpointStore 协议 —— 让 web/desktop 各自实现存储
    limits/           RateLimiter 协议 + 进程内无锁令牌桶
    storage/session   FastAPI 的会话依赖（get_session）
"""

# ── AI-ASSISTED ── 本文件由 AI 生成/改写，待人工复核 ──
# 复核重点：
#   1. ★ 上面"红线改了"那一段是**我的判断**，不是原作者的意图。
#      我把"零框架"改成"零存储后端"，理由是前者实测不成立。
#      **如果你不同意**（比如你宁愿把 models.py / session.py 赶出 core），
#      告诉我，我按你的来 —— 那会牵动两个 app 的导入。
#   2. 包根"零 import"是有意设计。如果你希望 `from furina_core import LocalTokenBucket`
#      这种短路径能用，就得放弃这一点，代价是 `import furina_core` 会把 bcrypt 也加载进来。
#   3. 模块地图是**手工维护**的，会漂移。加模块时记得同步。

__version__ = "0.1.0"

__all__ = ["__version__"]

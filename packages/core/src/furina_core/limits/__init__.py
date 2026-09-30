"""限流子包。

当前只有一个实现：`LocalTokenBucket`（进程内，桌面端用）。

web 端的分布式限流**刻意不在这里**：它最终由 Rust 网关的令牌桶承担
（与 Tauri 同栈，理由见仓库 PLAN 的分层决策）。在此之前，web 可以直接复用
本实现做单实例限流 —— 语义弱一点，但接口一致，将来换实现不动调用方。
"""

# ── AI-ASSISTED ── 本文件由 AI 生成/改写，待人工复核 ──
# 复核重点：这是包内**唯一有 import 副作用**的 `__init__.py`——
# 它会同时加载 base 和 local_bucket。将来加"Redis 实现"时要想清楚：
# 是放在这里一起 import（那 desktop 就白拿一个 redis 依赖），
# 还是让调用方自己显式 import 子模块。我倾向后者，但没替你决定。

from furina_core.limits.base import RateLimitExceeded, RateLimiter
from furina_core.limits.local_bucket import LocalTokenBucket

__all__ = ["RateLimitExceeded", "RateLimiter", "LocalTokenBucket"]

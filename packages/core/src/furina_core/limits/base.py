"""限流器的共同接口 —— 让"桌面进程内"和"web 分布式"可以互换。

桌面端（Tauri + 本地服务）与 web 端的限流目标**不一样**，这点必须先讲清楚：

    桌面端：单用户本地应用，**本地端口没有滥用者**。
            真正要限的是**出站 LLM 调用** —— 防成本失控、防撞供应商速率限制。
            -> 进程内令牌桶足够，不需要 Redis、不需要网络。

    web 端：多用户公网入口，要限的是**入站滥用**（撞库、爬取、放大计费）。
            -> 需要分布式配额，最终由 Rust 网关的令牌桶承担（与 Tauri 同栈）。

两者用同一个 `RateLimiter` 协议表达，实现各自选。调用方只依赖协议。
"""

# ── AI-ASSISTED ── 本文件由 AI 生成/改写，待人工复核 ──
# 复核重点：
#   1. `RateLimiter` 是 Protocol，**没有运行时强制力** —— 一个不满足契约的类
#      照样能当参数传进去，只在类型检查器下才报错。项目现在没装 mypy/pyright，
#      所以这层约束**目前是纯文档**。知道这一点再决定要不要装类型检查。
#   2. `try_acquire` 我定义成"返回 bool"（不抛异常），而 `acquire` 超时才抛
#      `RateLimitExceeded`。两者语义不对称是有意的（非阻塞失败是常态，
#      不算异常）。请确认你认同这个取舍。

from __future__ import annotations

from typing import Protocol, runtime_checkable


class RateLimitExceeded(Exception):
    """配额不足且调用方要求"不等待"。"""

    def __init__(self, *, key: str, retry_after: float) -> None:
        self.key = key
        self.retry_after = retry_after
        super().__init__(f"[{key}] 触发限流，约 {retry_after:.2f}s 后可重试")


@runtime_checkable
class RateLimiter(Protocol):
    """令牌桶限流器的最小契约。

    两个方法对应两种调用意图，**不要合并**：

    - `try_acquire()`：立即决策。拿不到就返回 False / 抛异常，调用方自己决定降级还是报错。
    - `acquire()`：愿意等待。等到有令牌再继续，可设超时。
    """

    @property
    def key(self) -> str:
        """这个桶的名字（用于日志与观测）。"""
        ...

    async def try_acquire(self, tokens: int = 1) -> bool:
        """非阻塞取令牌。拿到 True，拿不到 False（不抛异常）。"""
        ...

    async def acquire(self, tokens: int = 1, *, timeout: float | None = None) -> None:
        """阻塞取令牌；`timeout` 内取不到则抛 `RateLimitExceeded`。"""
        ...

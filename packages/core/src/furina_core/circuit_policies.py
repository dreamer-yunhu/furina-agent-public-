"""熔断器的两种降级策略 —— 框架无关。

来源：`backend/app/core/fuse_helpers.py`。原版硬绑 `redis.RedisError` + `fastapi.HTTPException`，
移植时把两者都摘掉：

- **不再 import fastapi**：core 只负责"吞还是抛"，HTTP 状态码由各 app 自己映射。
  web：`except CircuitOpenError: raise HTTPException(503, ...)`
  desktop：`except CircuitOpenError: return 降级结果`（本地应用没有 503 这个概念）
- **不再 import redis**：判断依据从"是不是 Redis 错误"改成"下游报了什么"。

⚠️ 语义差异（有意为之）：原版只把 `RedisError` 当作"降级信号"，
   其它异常会穿透。这里把所有非 `CircuitOpenError` 的异常都视为"下游不可用"。
   理由是：core 不知道下游是 Redis 还是 LLM 还是文件系统，而**对调用方来说，
   "后端炸了"和"后端超时了"应当走同一条降级路径**。需要更细的区分时，
   在调用方自己 try/except，别把策略塞进 core。
"""

# ── AI-ASSISTED ── 本文件由 AI 生成/改写，待人工复核 ──
# 复核重点：
#   1. `fail_open` 现在捕获**所有** Exception（原版只捕获 RedisError）。
#      这是扩大了口子：**代码 bug（TypeError 等）也会被当成"下游不可用"而静默降级**。
#      对你来说这是最值得推翻的一处 —— 如果你希望 bug 能炸出来，就把 `except Exception`
#      收窄成具体的下游异常类型。
#   2. `fail_closed` 刻意不吞异常。请确认调用方真的会处理它 ——
#      如果调用方也吞掉，鉴权就会在熔断时静默放行（安全漏洞）。
#   3. 两个函数都用了 `*args` 透传，**不支持 kwargs**（沿袭原版）。
#      将来要传关键字参数时会静默失败，建议现在就补 `**kwargs` 或明确拒绝。

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from furina_core.circuit_breaker import CircuitBreaker, CircuitOpenError

logger = logging.getLogger(__name__)

T = TypeVar("T")

Action = str


async def fail_open(
    breaker: CircuitBreaker,
    fn: Callable[..., Awaitable[T]],
    default: T,
    *args: Any,
    action: Action = "下游调用",
) -> T:
    """**降级**策略：下游不可用时返回 `default`，主流程继续。

    用于"没有它也能活"的东西：缓存读写、检索增强、非关键装饰性数据。

        history = await fail_open(breaker, get_hot_message, [], redis, conv_id)
    """
    try:
        return await breaker(fn, *args)
    except CircuitOpenError:
        logger.warning("[%s] 熔断中，%s 降级为默认值", breaker.name, action)
        return default
    except Exception:
        logger.warning("[%s] 下游异常，%s 降级为默认值", breaker.name, action, exc_info=True)
        return default


async def fail_closed(
    breaker: CircuitBreaker,
    fn: Callable[..., Awaitable[T]],
    *args: Any,
    action: Action = "下游调用",
) -> T:
    """**拒绝**策略：下游不可用时把异常抛给调用方，由它转成错误响应。

    用于"没有它就不能安全继续"的东西：鉴权黑名单、会话对账、权限校验。

        is_banned = await fail_closed(breaker, is_blocklisted, redis, jti)
        # 调用方：except (CircuitOpenError, ...) -> 503 / 拒绝放行

    ⚠️ 这里刻意**不吞异常**：fail-closed 的全部意义就是"不确定就拒绝"。
       如果这里吞掉，鉴权会在 Redis 挂掉时静默放行，那是安全漏洞而不是降级。
    """
    try:
        return await breaker(fn, *args)
    except CircuitOpenError:
        logger.warning("[%s] 熔断中，%s 拒绝执行（fail-closed）", breaker.name, action)
        raise
    except Exception:
        logger.warning("[%s] 下游异常，%s 拒绝执行（fail-closed）", breaker.name, action, exc_info=True)
        raise

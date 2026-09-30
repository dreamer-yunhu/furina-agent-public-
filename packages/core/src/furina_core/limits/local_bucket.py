"""进程内令牌桶 —— 无锁实现，桌面端用来限出站 LLM 调用。

═══════════════════════════════════════════════════════════════════════
一、先讲"令牌桶"到底是什么（限流的最基础模型）
═══════════════════════════════════════════════════════════════════════

想象一个桶，桶里最多装 `capacity` 个硬币：

    · 每来一个请求，就从桶里拿走 1 个硬币（拿不到 = 被限流）
    · 桶里的硬币以每秒 `refill_rate` 个的速度**自动恢复**
    · 桶满了就不再增加（不会攒超过 capacity 个）

这两个参数管的是**两件不同的事**，这是最容易搞混的地方：

    capacity    = 允许多快的"突发"（瞬时连打几次）
    refill_rate = 允许多快的"稳态"（长期平均每秒几次）

    例：capacity=5, refill_rate=1.0
        -> 长期平均每秒 1 次
        -> 但空闲一阵攒满 5 个后，可以一口气连打 5 次

为什么选令牌桶而不是"每秒计数"（固定窗口）？因为固定窗口有**边界突刺**问题：
窗口是 [0s,1s) 和 [1s,2s)，在 0.99s 打 5 次、1.01s 又打 5 次 —— 两个窗口各自
都没超限，但 0.02 秒内实际打了 10 次。令牌桶没有这个缝。

═══════════════════════════════════════════════════════════════════════
二、"无锁"是怎么成立的（本模块最核心的一点，值得反复看）
═══════════════════════════════════════════════════════════════════════

先破除一个直觉误区：**"无锁"不等于"没有临界区"**。

临界区（critical section）= 一段"不能被中途打断"的代码。
在多线程里，打断来自**线程调度**；在 asyncio 里，打断来自**await**。

    asyncio 的事件循环是【单线程】的。
    一个协程只有执行到 await 时，才会把控制权交出去，别的协程才有机会跑。

所以结论是：

    只要一段代码里【一次 await 都没有】，
    它从第一行执行到最后一行，中间绝不会被别的协程插进来。
    —— 这段同步代码，本身就是一个原子的临界区。

这就是本模块的设计根据。具体体现为一条硬约束：

    ⚠️ `_refill_and_take()` 里【绝对不允许出现 await】。

"读当前令牌数 → 按流逝时间补充 → 扣减"这三步必须一口气做完。
一旦中间插进一个 await，别的协程就能看到"补充了一半"的中间状态，
计数立刻错乱。

【反面教材】——为什么不能"为了看起来安全"而加锁：

    async def try_acquire(self):
        async with self._lock:          # ← 加锁
            await something()           # ← 锁里面出现 await
            self._take()                # ← 已经不安全了

只要锁保护的代码段里出现了 await，锁就形同虚设（甚至更糟：你以为安全了）。
正确做法是**让临界区保持同步**，而不是给它包一层 async 的壳。

═══════════════════════════════════════════════════════════════════════
三、为什么用"惰性补充"而不是后台定时器
═══════════════════════════════════════════════════════════════════════

"每秒恢复 1 个硬币"有两种实现思路：

    方案 A：起一个 asyncio 后台任务，每 0.1 秒醒来给桶加 0.1 个硬币
    方案 B（本模块）：不主动加。等有人来取的时候，用"距离上次更新过了多久"
                      现算该补多少（lazy refill / 惰性补充）

方案 B 的好处很实在：
    · 不需要创建 asyncio.Task -> 不会有"任务泄漏"（忘了取消的后台任务）
    · 程序关闭时不需要额外清理逻辑
    · 桶没人用时零开销（不占 CPU、不占定时器）
    · 少一个并发源，少一类 bug

代价：桶的"当前值"只在被访问时才更新。所以 `snapshot()` 里看到的数字
     可能偏旧 —— 对限流用途完全无影响。这是**用一点精度换掉一整类并发问题**。

═══════════════════════════════════════════════════════════════════════
四、和原始代码的关系
═══════════════════════════════════════════════════════════════════════

`backend/app/core/redis_limiter.py` 里的 `TokenBucketLimiter` 是一个**空壳**：
只有 `__init__`，没有任何取值方法，而且全项目零引用 —— 也就是说"限流"从来
没有真正生效过。

所以这个文件不是"移植"，是**补上实现**。分布式版本（Redis + Lua，多实例共享
配额）服务的是 web 的多用户场景，最终由 Rust 网关接管；桌面端单用户用不上。
"""

# ── AI-ASSISTED ── 本文件由 AI 生成/改写，待人工复核 ──
# 复核重点（已通过 scripts/verify_core.py 的 6 项验证，但仍请自己读）：
#   1. `_refill_and_take` 里**绝对不能有 await**（见上面第二节）。
#      整个"无锁"的正确性全押在这一条上。这是靠注释约束的，不是类型系统。
#   2. `acquire()` 是"小步 sleep + 重试"轮询，不是事件驱动。
#      代价：最多 _MAX_POLL=0.2s 的额外延迟。我认为对限流足够，
#      但如果你要精确到毫秒，得换成 asyncio.Condition + 定时唤醒。
#   3. `initial_tokens` 默认给满桶。想让"启动即限流"就传 0。

from __future__ import annotations

import asyncio
import logging
import time

from furina_core.limits.base import RateLimitExceeded

logger = logging.getLogger(__name__)

# ----------------------------------------------------------------------
# 轮询间隔的两个边界。数值选择有讲究，别随手改：
#   太小 -> 空转烧 CPU
#   太大 -> 令牌明明已经补上了，我们还在睡，白白多等
# 取 [5ms, 200ms]：5ms 足够细，200ms 的上限保证不会"睡过头"太多。
# ----------------------------------------------------------------------
_MIN_POLL = 0.005
_MAX_POLL = 0.2


class LocalTokenBucket:
    """单进程令牌桶。

    参数：

        capacity        桶容量 = 允许的瞬时突发量（不是速率！）
        refill_rate     每秒补充的令牌数 = 稳态速率
        key             桶名，只用于日志和观测
        initial_tokens  初始令牌数，默认填满

    用法：

        bucket = LocalTokenBucket(capacity=5, refill_rate=1.0, key="llm")

        # 用法一：不等待，拿不到就算了（适合"降级"）
        if await bucket.try_acquire():
            await call_llm()
        else:
            return "请求太频繁了，稍后再试"

        # 用法二：愿意等（适合"必须执行但可以慢一点"）
        await bucket.acquire(timeout=30)
        await call_llm()
    """

    def __init__(
        self,
        *,
        capacity: int,
        refill_rate: float,
        key: str = "local",
        initial_tokens: float | None = None,
    ) -> None:
        # ---- 参数校验：错配的参数应该在构造时就炸，而不是运行期产生怪异行为 ----
        if capacity <= 0:
            raise ValueError("capacity 必须为正整数")
        if refill_rate <= 0:
            # 为什么必须 > 0：如果补充速率是 0，桶一旦空了就永远填不满，
            # `acquire()` 会无限等待 —— 这是死锁，不是限流。
            raise ValueError("refill_rate 必须为正数（每秒补充的令牌数）")

        self._key = key
        # 用 float 而不是 int 存令牌数：因为惰性补充会算出小数
        # （比如过了 0.3 秒、速率 1.0 -> 补 0.3 个）。用 int 会把小数丢掉，
        # 高频调用下误差会累积成明显的偏差。
        self._capacity = float(capacity)
        self._refill_rate = float(refill_rate)
        self._tokens = self._capacity if initial_tokens is None else float(initial_tokens)
        # time.monotonic() 而不是 time.time()：
        #   time.time() 是"墙上时钟"，会被系统对时/NTP 调整，可能倒退。
        #   算时间差必须用单调时钟，否则时钟回拨会让 elapsed 变成负数。
        self._updated_at = time.monotonic()

    # ==================================================================
    # 只读视图
    # ==================================================================
    @property
    def key(self) -> str:
        return self._key

    @property
    def capacity(self) -> float:
        return self._capacity

    @property
    def refill_rate(self) -> float:
        return self._refill_rate

    def snapshot(self) -> dict[str, float | str]:
        """给日志/健康检查用的快照。

        注意：这里**故意只读**，不调用 `_refill_and_take` ——
        观测行为不应该产生副作用（否则看一眼监控就改变了限流状态）。
        代价是 tokens 显示的是"上次访问时"的值，可能偏旧。
        """
        return {
            "key": self._key,
            "tokens": self._tokens,
            "capacity": self._capacity,
            "refill_rate": self._refill_rate,
            "idle_seconds": time.monotonic() - self._updated_at,
        }

    # ==================================================================
    # 核心临界区 —— ⚠️ 同步方法，不准出现 await
    # ==================================================================
    def _refill_and_take(self, tokens: int) -> bool:
        """补充令牌并尝试扣减。返回是否成功。

        ⚠️⚠️ 本方法是整个"无锁"设计的承重点，**必须保持同步**。
             一旦插入 await，第二节讲的单线程原子性就没了。
        """
        now = time.monotonic()

        # ---- 第 1 步：惰性补充 ----
        elapsed = now - self._updated_at
        if elapsed > 0:
            # min(..., capacity) 就是"桶满了不再增加"。
            # 没有这个 min，桶会无限攒令牌，突发限制就失效了。
            self._tokens = min(self._capacity, self._tokens + elapsed * self._refill_rate)
            # 注意这一行必须在同一个 if 里：如果 elapsed <= 0（时钟异常）就不更新
            # 时间戳，避免把 _updated_at 往前推、反而"抹掉"了本该补的令牌。
            self._updated_at = now

        # ---- 第 2 步：够就扣，不够就如实返回 False ----
        if self._tokens >= tokens:
            self._tokens -= tokens
            return True
        return False

    def _wait_seconds(self, tokens: int) -> float:
        """还差多少秒才够 `tokens` 个令牌。只用于估算等待时间。"""
        missing = tokens - self._tokens
        if missing <= 0:
            return 0.0
        return missing / self._refill_rate

    # ==================================================================
    # 公开接口（对应 limits/base.py 里的 RateLimiter 协议）
    # ==================================================================
    async def try_acquire(self, tokens: int = 1) -> bool:
        """非阻塞取令牌：拿到 True，拿不到 False。

        注意这个方法虽然是 `async def`，但函数体里**一个 await 都没有** ——
        所以它的"检查 + 扣减"是原子的。声明成 async 只是为了和 `acquire()`
        保持同一个调用形状（调用方不用记"哪个要 await"）。
        """
        if tokens <= 0:
            raise ValueError("tokens 必须为正整数")
        if tokens > self._capacity:
            # 一次要的令牌超过桶容量 = 永远不可能满足。
            # 这种情况立刻报错，而不是让调用方永远等下去 ——
            # 那会变成死锁，而且很难排查（表现为"卡住"而不是"报错"）。
            raise ValueError(f"请求 {tokens} 个令牌超过桶容量 {self._capacity:g}，永远无法满足")
        return self._refill_and_take(tokens)

    async def acquire(self, tokens: int = 1, *, timeout: float | None = None) -> None:
        """阻塞直到取到令牌；`timeout` 秒内取不到则抛 `RateLimitExceeded`。

        为什么用"小步 sleep + 重试"轮询，而不是 asyncio.Condition（条件变量）？

            条件变量的标准用法是"等的人 await cond.wait()，改状态的人 cond.notify()"。
            但这里有个根本问题：**令牌是按时间自然恢复的，没有"改状态的人"**。
            没有唤醒方，notify 就无从触发。想让 Condition 工作，就得再起一个
            定时任务去 notify —— 那又回到了"后台定时器"方案，把它要避免的问题
            （任务泄漏、需要清理）全带回来了。

            所以轮询在这个场景不是偷懒，是**更简单也更正确的选择**。
        """
        if tokens <= 0:
            raise ValueError("tokens 必须为正整数")
        if tokens > self._capacity:
            raise ValueError(f"请求 {tokens} 个令牌超过桶容量 {self._capacity:g}，永远无法满足")

        # 超时的判定基准。用 monotonic 累加，避免每次循环重新算导致漂移。
        deadline = None if timeout is None else time.monotonic() + timeout

        while True:
            # ---- 先试一次：能立刻拿到就不进等待逻辑（绝大多数情况走这条路）----
            if self._refill_and_take(tokens):
                return

            # ---- 拿不到，算算要等多久 ----
            need = self._wait_seconds(tokens)

            if deadline is not None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise RateLimitExceeded(key=self._key, retry_after=need)
                # 别睡过超时的时刻，否则超时会"迟到"
                sleep_for = min(need, remaining)
            else:
                sleep_for = need

            # 夹在 [MIN_POLL, MAX_POLL] 之间：
            #   下限防止 sleep_for≈0 时空转烧 CPU
            #   上限防止睡太久 —— 我们睡觉期间桶还在恢复，
            #   醒来时可能早就有令牌了，睡 1 秒就白白慢了 1 秒
            await asyncio.sleep(max(_MIN_POLL, min(sleep_for, _MAX_POLL)))

    # ==================================================================
    # 便利方法
    # ==================================================================
    async def __call__(self, tokens: int = 1) -> bool:
        """`await bucket()` 等价于 `await bucket.try_acquire()`。

        加这个是为了和 CircuitBreaker 的调用形状一致（都是 `await obj(...)`），
        调用方不用记两套写法。
        """
        return await self.try_acquire(tokens)

    def reset(self) -> None:
        """把桶重新填满。给测试和运维用。

        原始实现没有任何"手动复归"的口子，只能干等 —— 那对测试很不友好。
        """
        self._tokens = self._capacity
        self._updated_at = time.monotonic()

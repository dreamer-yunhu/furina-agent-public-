"""三态熔断器 —— 进程内状态机，零外部依赖。

═══════════════════════════════════════════════════════════════════════
一、熔断器解决什么问题
═══════════════════════════════════════════════════════════════════════

下游挂了（超时、连接拒绝、5xx 刷屏），如果还一直往里打请求，会发生三件坏事：

    1. 调用方被拖死 —— 每个请求都要等满超时时间才失败
    2. 下游被压死 —— 它本来只是"慢"，被重试打成"死"
    3. 故障扩散   —— 上游的线程/连接被占满，于是上游也挂了（雪崩）

熔断器的思路来自电路保险丝：**连续失败到一定次数，就直接跳闸切断**。
之后请求快速失败（不触达下游），过一段时间再放少量请求**试探**，
好了就恢复，不好就继续断。

═══════════════════════════════════════════════════════════════════════
二、三个状态和迁移条件
═══════════════════════════════════════════════════════════════════════

    CLOSE（闭合，正常工作）
        │  连续失败次数 >= fail_threshold  →  跳闸
        ▼
    OPEN（断开，快速失败）
        │  经过 cooldown_seconds 冷却时间
        ▼
    HALF_OPEN（半开，试探期）
        ├─ 连续成功 >= probe_success  → 恢复 CLOSE
        └─ 累计失败 >= probe_failure  → 退回 OPEN

为什么要 HALF_OPEN 这个中间态？不能直接从 OPEN 跳回 CLOSE 吗？

    因为"冷却时间到了"只说明时间过去了，**不说明下游好了**。
    如果直接恢复全量流量，下游没好的话会立刻被二次打垮。
    HALF_OPEN 的作用就是"先放几个探子过去"——
    成本极低（几个请求），但能避免盲目恢复。

═══════════════════════════════════════════════════════════════════════
三、⭐ 为什么这里需要锁，而令牌桶不需要（最值得对比理解的一点）
═══════════════════════════════════════════════════════════════════════

两个文件都是 asyncio 下的并发安全代码，但一个无锁、一个加锁。区别在**临界区
里有没有 await**，这是判断"要不要加锁"的唯一标准：

    令牌桶（无锁）：
        try_acquire() 里没有任何 await
        -> "读计数 + 补充 + 扣减"一口气做完
        -> 天然原子，不需要锁

    熔断器（要锁）：
        __call__() 必须【先 await 下游调用】，然后【再根据结果改状态】
        -> 中间那个 await 是绕不开的（它就是下游调用本身！）
        -> 别的协程能在这个 await 处插进来
        -> 必须用锁保护"读状态"和"写状态"这两段

【具体会出什么错】原版 `RedisFuse` 没有锁，10 个请求同时失败时会发生：

    协程1: 读 _fail_count = 0  →  ...
    协程2: 读 _fail_count = 0  →  ...        ← 两个都读到 0
    协程1: _fail_count = 1
    协程2: _fail_count = 1                    ← 两次失败，只记了 1 次

结果就是：配置"连续失败 5 次跳闸"，实际要失败 8 次才跳。
**这个 bug 只会让熔断变慢，不会报错 —— 属于最难发现的那一类。**
（scripts/verify_core.py 里有一条 "10 concurrent failures -> tripped" 专门验这个）

【加锁的正确姿势】锁要包住**读-改-写**这一整段，而不是只包住写：

    ✅ 正确：async with lock: 读状态; 判断; 改状态
    ❌ 错误：读状态; async with lock: 改状态      ← 读和写之间仍可被插入

所以本文件里所有 `*_locked` 后缀的方法都必须**在持锁状态下调用**（见第四节）。

═══════════════════════════════════════════════════════════════════════
四、状态机：为什么异常要对调用方透明
═══════════════════════════════════════════════════════════════════════

熔断器**不是**异常处理器。它的职责只有两个：

    · 记录成败，驱动状态迁移
    · 跳闸期间快速失败

**它绝不吞掉下游的异常**。下游抛什么，它就往上抛什么（`raise` 原样透传）。
理由：熔断器不知道调用方想怎么处理这个错误 —— 是重试？降级？还是返回 500？
那是调用方的决定。熔断器擅自吞掉，就是越权。

降级策略在另一个文件（`circuit_policies.py` 的 `fail_open` / `fail_closed`），
那里才是"决定怎么办"的地方。**职责分离**：
    熔断器  = 要不要打这个下游
    fail_*  = 决定不打（或打失败）之后怎么办
"""

# ── AI-ASSISTED ── 本文件由 AI 生成/改写，待人工复核 ──
# 复核重点（已通过 scripts/verify_core.py 的 6 项验证）：
#   1. ⭐ 加了 `asyncio.Lock`（`_state_lock`）。原版没有，10 并发失败会丢计数。
#      请确认：三个 `_locked` 结尾的方法**只在持锁时被调用** ——
#      这是靠命名约定，不是靠类型系统。漏一处 = 竞态回来。
#   2. `except CircuitOpenError: raise` 是我加的。请想清楚：
#      如果下游自己**也抛** CircuitOpenError（比如嵌套了另一个熔断器），
#      这个异常就不会被计为失败。这是有意的还是漏洞？你自己判断。
#   3. 阈值默认值（5 次 / 10 秒 / 3 / 3）我从原版原样搬来，**没有重新评估**。
#      它们合不合理取决于下游是谁 —— 建议按 DeepSeek 的实际超时时间重新定。

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any, Literal, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")

# 用 Literal 而不是 Enum：这个项目里两种写法都有过（见 models/table.py 的
# MessageRole 用了 Enum，state.py 的 mode 用了 Literal）。
# 这里选 Literal 是因为只要三个字面量、不需要方法，Enum 是多余的仪式。
# ⚠️ 但注意：Literal 只是**静态检查**，运行期传个 "CLOSE2" 也不会报错。
CircuitState = Literal["CLOSE", "OPEN", "HALF_OPEN"]


class CircuitOpenError(Exception):
    """熔断短路：OPEN 期间拒绝访问下游。

    注意它**不是**"下游报错了"，而是"我压根没去打下游"。
    这个区别对调用方很重要：前者说明下游有问题，后者说明我们在保护它。
    """


class CircuitBreaker:
    """三态熔断器。**一个实例 = 一条下游链路**。

    想给不同的下游各自独立熔断，就各建一个实例 —— 别共用一个：

        llm_breaker    = CircuitBreaker(name="llm",    fail_threshold=3)
        search_breaker = CircuitBreaker(name="search", fail_threshold=5)

    共用的话，搜索挂了会把 LLM 的调用也一起断掉 —— 那是误伤。

    用法：

        breaker = CircuitBreaker(name="llm")
        try:
            result = await breaker(call_llm, prompt)
        except CircuitOpenError:
            # 熔断中，压根没调下游。这里决定降级策略
            ...
        except Exception:
            # 真调了下游，下游报的错。原样往上抛或自己处理
            ...
    """

    # 用类属性存常量，避免在代码里到处写魔法字符串。
    # 好处：拼错时 IDE 会提示（写 self.CLOSED 而不是 self.CLOSE，立刻能发现）。
    CLOSE: CircuitState = "CLOSE"
    OPEN: CircuitState = "OPEN"
    HALF_OPEN: CircuitState = "HALF_OPEN"

    def __init__(
        self,
        *,
        name: str = "downstream",
        fail_threshold: int = 5,
        cooldown_seconds: float = 10.0,
        probe_success: int = 3,
        probe_failure: int = 3,
    ) -> None:
        self.name = name
        self._fail_threshold = fail_threshold
        self._cooldown_seconds = cooldown_seconds
        self._probe_success = probe_success
        self._probe_failure = probe_failure

        # ---- 状态与计数器。这五个字段都是"读-改-写"模式，全部受锁保护 ----
        self._state: CircuitState = self.CLOSE
        self._fail_count = 0        # CLOSE 下的连续失败数
        self._probe_ok_count = 0    # HALF_OPEN 下的连续成功数
        self._probe_fail_count = 0  # HALF_OPEN 下的累计失败数
        self._opened_at = 0.0       # 进入 OPEN 的时刻（monotonic，不是墙上时间）

        # ---- 那把锁（见模块 docstring 第三节）----
        # 用 asyncio.Lock 而不是 threading.Lock：这里是 asyncio 单线程环境，
        # threading.Lock 会阻塞整个事件循环，反而制造问题。
        self._state_lock = asyncio.Lock()

    # ==================================================================
    # 只读视图（不需要锁：读单个属性不会有"读到一半"的问题）
    # ==================================================================
    @property
    def state(self) -> CircuitState:
        return self._state

    @property
    def is_open(self) -> bool:
        return self._state == self.OPEN

    def snapshot(self) -> dict[str, Any]:
        """结构化快照，给 /health 或日志用。

        原版是靠解析日志字符串来判断状态的（"连续失败 5 次，熔断 OPEN"）——
        那是人看的格式，程序不该去解析它。这个方法是程序友好的替代。
        """
        return {
            "name": self.name,
            "state": self._state,
            "fail_count": self._fail_count,
            "probe_ok": self._probe_ok_count,
            "probe_fail": self._probe_fail_count,
            "opened_at": self._opened_at,
        }

    # ==================================================================
    # 状态迁移 —— ⚠️ 以下方法【必须在持锁状态下调用】
    # 命名用 _locked 后缀作为提醒（这是约定，不是编译器强制）
    # ==================================================================
    def _on_failure_locked(self) -> None:
        """记一次失败。CLOSE 下累计，HALF_OPEN 下探测失败。"""
        if self._state == self.CLOSE:
            self._fail_count += 1
            if self._fail_count >= self._fail_threshold:
                self._state = self.OPEN
                self._opened_at = time.monotonic()
                # ⚠️ 顺序有讲究：**先打日志，再归零**。
                # 反过来的话（先归零再打日志），日志里永远显示 0 次 ——
                # 原版代码的注释里专门记过这个坑。
                logger.warning(
                    "[%s] 连续失败 %d 次，熔断 -> OPEN（冷却 %.1fs）",
                    self.name,
                    self._fail_count,
                    self._cooldown_seconds,
                )
                self._fail_count = 0
        elif self._state == self.HALF_OPEN:
            self._probe_fail_count += 1
            if self._probe_fail_count >= self._probe_failure:
                self._state = self.OPEN
                self._opened_at = time.monotonic()
                self._probe_ok_count = 0
                self._probe_fail_count = 0
                logger.warning("[%s] 探测失败，HALF_OPEN -> OPEN", self.name)
        # 注意：OPEN 状态下不会再调这个方法（调用前已经被 _admit_locked 拦住），
        # 所以这里不需要处理 OPEN 分支。

    def _on_success_locked(self) -> None:
        """记一次成功。"""
        if self._state == self.CLOSE:
            # 连续失败的定义：成功一次就清零。
            # 如果不清零，就成了"累计失败"而不是"连续失败"，
            # 那样一个长期偶发失败的下游会被误判为故障。
            self._fail_count = 0
        elif self._state == self.HALF_OPEN:
            self._probe_ok_count += 1
            if self._probe_ok_count >= self._probe_success:
                self._state = self.CLOSE
                logger.info(
                    "[%s] 探测成功 %d 次，HALF_OPEN -> CLOSE",
                    self.name,
                    self._probe_ok_count,
                )
                # 三个计数器全部清零，避免残留值影响下一轮判断
                self._fail_count = 0
                self._probe_fail_count = 0
                self._probe_ok_count = 0

    async def _admit_locked(self) -> None:
        """门闸：决定这次调用能不能放行。**必须在持锁状态下调用**。

        三种结果：
            CLOSE     -> 直接放行
            HALF_OPEN -> 直接放行（处于试探期）
            OPEN      -> 冷却到了就转 HALF_OPEN 放行，否则抛 CircuitOpenError
        """
        if self._state != self.OPEN:
            return

        if time.monotonic() - self._opened_at >= self._cooldown_seconds:
            self._state = self.HALF_OPEN
            self._probe_ok_count = 0
            self._probe_fail_count = 0
            logger.info("[%s] 冷却结束，OPEN -> HALF_OPEN 试探期", self.name)
            return

        # 还在冷却期内 -> 快速失败，**不触达下游**
        raise CircuitOpenError(f"[{self.name}] 熔断中，拒绝访问")

    # ==================================================================
    # 主入口
    # ==================================================================
    async def __call__(
        self,
        fn: Callable[..., Awaitable[T]],
        *args: Any,
        **kwargs: Any,
    ) -> T:
        """执行 `fn`（下游调用），并由其结果驱动状态机。

        注意这里 `*args, **kwargs` 的透传方式：调用方写

            await breaker(call_llm, prompt, timeout=30)

        这正是 TypeVar[T] 的用途 —— 返回值类型跟着 `fn` 走，
        调用方不需要做任何类型转换。
        """
        # ---- 第一段临界区：只做"门闸判断"，不含下游调用 ----
        # 为什么不把下游调用也放进锁里？因为那会**串行化所有请求** ——
        # 加锁的意义是保护状态，不是限制并发。下游该并发就得并发。
        async with self._state_lock:
            await self._admit_locked()

        # ---- 下游调用：在锁外面，可以并发 ----
        try:
            result = await fn(*args, **kwargs)
        except CircuitOpenError:
            # 熔断器自己抛的不算下游失败。否则会出现：
            # "熔断中 -> 被当成失败 -> 计数增加 -> 更长时间熔断" 的自我强化。
            raise
        except Exception:
            # 其它一切都算失败（见模块 docstring 的取舍说明）
            async with self._state_lock:
                self._on_failure_locked()
            raise  # ⚠️ 原样往上抛，绝不吞掉（见 docstring 第四节）

        # ---- 第三段临界区：记成功 ----
        async with self._state_lock:
            self._on_success_locked()
        return result

    def reset(self) -> None:
        """手动复归到 CLOSE。

        原版没有这个能力，跳闸后只能干等冷却 —— 测试和运维都不方便。

        注意：这里**不加锁**。因为它是同步方法，没有 await，
        在 asyncio 单线程下本身就是原子的（和令牌桶同一个道理）。
        """
        self._state = self.CLOSE
        self._fail_count = 0
        self._probe_ok_count = 0
        self._probe_fail_count = 0
        self._opened_at = 0.0
        logger.info("[%s] 手动复归 -> CLOSE", self.name)

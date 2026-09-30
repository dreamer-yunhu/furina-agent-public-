"""core 的可运行自测 —— 纯 ASCII 输出，避免控制台编码问题。

用法（在仓库根）：
    .venv-build\\Scripts\\python.exe scripts\\verify_core.py

这个脚本是 AI 写的验证脚手架，验完可以删。
"""

import asyncio
import time

from furina_core.circuit_breaker import CircuitBreaker, CircuitOpenError
from furina_core.limits import LocalTokenBucket, RateLimitExceeded

PASS = "PASS"
FAIL = "FAIL"


def check(label: str, actual, expected) -> None:
    ok = actual == expected
    print(f"  [{PASS if ok else FAIL}] {label:<38} got={actual!r} want={expected!r}")


async def test_bucket() -> None:
    print("=== LocalTokenBucket ===")
    b = LocalTokenBucket(capacity=2, refill_rate=1.0, key="llm")

    r = [await b.try_acquire() for _ in range(3)]
    check("capacity=2, take 3 times", r, [True, True, False])

    t0 = time.monotonic()
    await b.acquire(timeout=5)
    elapsed = time.monotonic() - t0
    check("acquire waits ~1.0s for refill", 0.9 < elapsed < 1.3, True)

    try:
        await b.try_acquire(5)
        print(f"  [{FAIL}] over-capacity request should raise")
    except ValueError:
        print(f"  [{PASS}] over-capacity request raises ValueError")

    b.reset()
    ok1 = await b.try_acquire()
    ok2 = await b.try_acquire()
    try:
        await b.acquire(timeout=0.2)
        print(f"  [{FAIL}] timeout path should raise")
    except RateLimitExceeded as e:
        print(f"  [{PASS}] timeout raises RateLimitExceeded "
              f"(retry_after={e.retry_after:.2f}s)")

    check("reset() refilled the bucket", (ok1, ok2), (True, True))

    # 无锁的正确性：20 个协程并发抢 5 个令牌，恰好 5 个成功
    b2 = LocalTokenBucket(capacity=5, refill_rate=0.001, key="race")
    results = await asyncio.gather(*(b2.try_acquire() for _ in range(20)))
    check("20 concurrent tasks, capacity=5", sum(results), 5)


async def test_breaker() -> None:
    print()
    print("=== CircuitBreaker ===")
    br = CircuitBreaker(name="llm", fail_threshold=2, cooldown_seconds=0.3,
                        probe_success=2, probe_failure=1)

    async def boom():
        raise RuntimeError("downstream failed")

    async def ok():
        return "fine"

    for _ in range(2):
        try:
            await br(boom)
        except RuntimeError:
            pass
    check("after 2 failures (threshold=2)", br.state, "OPEN")

    try:
        await br(ok)
        print(f"  [{FAIL}] OPEN should short-circuit")
    except CircuitOpenError:
        print(f"  [{PASS}] OPEN short-circuits without calling downstream")

    await asyncio.sleep(0.35)
    check("first probe after cooldown", await br(ok), "fine")
    check("state after 1 probe", br.state, "HALF_OPEN")
    await br(ok)
    check("state after 2 probes (probe_success=2)", br.state, "CLOSE")

    # 并发失败计数：10 个并发失败，阈值 2，必须跳闸（旧版会丢计数）
    br2 = CircuitBreaker(name="race", fail_threshold=2)

    async def boom2():
        raise RuntimeError("x")

    await asyncio.gather(*(br2(boom2) for _ in range(10)), return_exceptions=True)
    check("10 concurrent failures -> tripped", br2.state, "OPEN")


async def main() -> None:
    await test_bucket()
    await test_breaker()
    print()
    print("done.")


if __name__ == "__main__":
    asyncio.run(main())

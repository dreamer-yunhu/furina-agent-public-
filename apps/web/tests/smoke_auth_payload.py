# -*- coding: utf-8 -*-
"""鉴权 / 刷新 / 登出 的载荷冒烟测试（不需要 PG，也不需要 Redis）。

# ── AI-ASSISTED ── 本文件由 AI 生成，待人工复核 ──
# 复核重点：
#   1. 它防的是**这一种 bug**：core 的解码器返回 `TokenPayload`（dataclass）而不是 dict，
#      调用点写 `payload.get("sub")` 时 import/启动全都正常，只在**请求进来那一刻**
#      变成 500。同理，core 抛 `TokenError` 而不是 `HTTPException`，没接住就是 500。
#      → 所以断言全部落在"状态码"和"令牌类型"上，不验业务逻辑。
#   2. 它**打桩了三处模块级名字**（`deps.is_blocklisted` / `deps.is_current_session` /
#      `deps.get_user_by_id`，以及 services 侧的对应名字）。FastAPI 的依赖注入与
#      `fuse_fail_closed` 都是"调用时按模块全局名解析"，所以打桩有效；但也意味着
#      **改了这些名字的导入方式，本测试会静默失效**（不报错、直接跑到真 Redis 上）。
#   3. 没有断言 503 分支（Redis 挂掉那条）：那需要真的让 fail_closed 抛错，属另一类用例。

用法（在仓库根）：

    $env:PYTHONPATH = "packages\\core\\src;apps\\web\\src;apps\\desktop\\src"
    .venv-build\\Scripts\\python.exe apps\\web\\tests\\smoke_auth_payload.py
"""
import asyncio
import os
import sys
import uuid
from datetime import timedelta

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

os.environ.setdefault("JWT_SECRET_KEY", "x" * 40)
os.environ.setdefault("JWT_ALGO", "HS256")

import httpx  # noqa: E402
from fastapi import Depends, FastAPI  # noqa: E402

from furina_core.circuit_breaker import CircuitBreaker  # noqa: E402
from furina_core.models import User  # noqa: E402
from furina_core.security import (  # noqa: E402
    TokenError,
    create_token,
    decode_token,
)

import furina_web.auth.dependencies as deps  # noqa: E402
import furina_web.services.user as svc  # noqa: E402

PASS, FAIL = "PASS", "FAIL"
results: list[tuple[str, bool, str]] = []


def check(label: str, cond: bool, extra: str = "") -> None:
    results.append((label, cond, extra))
    print(f"  [{PASS if cond else FAIL}] {label:<52} {extra}")


def make_token(token_type: str, *, subject: str | None = None, session_id=None, delta=timedelta(minutes=5), jti="jti-1"):
    return create_token(
        subject=subject or str(uuid.uuid4()),
        token_type=token_type,
        jwt_key="x" * 40,
        expires_delta=delta,
        session_id=session_id,
        extra_claims={"jti": jti},
    )


USER_ID = uuid.uuid4()
SESSION_ID = uuid.uuid4()
FAKE_USER = User(id=USER_ID, user_name="furina", hashed_password="x" * 60)


# ----------------------------------------------------------------------
# 打桩：门禁模块里的仓储调用
# ----------------------------------------------------------------------
async def fake_get_user_by_id(session, user_id):
    return FAKE_USER if str(user_id) == str(USER_ID) else None


async def fake_is_blocklisted(redis, jti):
    return False


async def fake_is_current_session(redis, session_id, user_id):
    return True


deps.is_blocklisted = fake_is_blocklisted
deps.is_current_session = fake_is_current_session
deps.get_user_by_id = fake_get_user_by_id

app = FastAPI()


@app.get("/me")
async def me(user=Depends(deps.get_current_user)):
    return {"id": str(user.id), "name": user.user_name}


app.dependency_overrides[deps.get_session] = lambda: object()
app.dependency_overrides[deps.get_redis] = lambda: object()
app.dependency_overrides[deps.get_redis_fuse] = lambda: CircuitBreaker(name="redis")


async def call_me(token: str):
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        return await c.get("/me", headers={"Authorization": f"Bearer {token}"})


print("=== 1. get_current_user（门禁） ===")


async def t_gate():
    ok = make_token("access", subject=str(USER_ID), session_id=str(SESSION_ID))
    r = await call_me(ok)
    check("合法 access 令牌 -> 200", r.status_code == 200, f"got {r.status_code} {r.text[:80]}")

    expired = make_token("access", subject=str(USER_ID), session_id=str(SESSION_ID), delta=timedelta(seconds=-10))
    r = await call_me(expired)
    check("过期令牌 -> 401（改前是 500）", r.status_code == 401, f"got {r.status_code} {r.text[:80]}")

    refresh = make_token("refresh", subject=str(USER_ID), session_id=str(SESSION_ID))
    r = await call_me(refresh)
    check("拿 refresh 当 access -> 401", r.status_code == 401, f"got {r.status_code} {r.text[:80]}")

    r = await call_me("garbage.token.here")
    check("乱码令牌 -> 401", r.status_code == 401, f"got {r.status_code} {r.text[:80]}")

    unknown = make_token("access", subject=str(uuid.uuid4()), session_id=str(SESSION_ID))
    r = await call_me(unknown)
    check("库里查不到的用户 -> 401", r.status_code == 401, f"got {r.status_code} {r.text[:80]}")


asyncio.run(t_gate())


# ----------------------------------------------------------------------
# user_refresh：直接调服务函数（打桩仓储 + 假 redis）
# ----------------------------------------------------------------------
class FakeRedis:
    def __init__(self):
        self.blocked: list[str] = []


async def fake_jwt_block_list(redis, token_jti, ttl):
    redis.blocked.append(token_jti)


svc.get_user_by_id = fake_get_user_by_id
svc.is_blocklisted = fake_is_blocklisted
svc.is_current_session = fake_is_current_session
svc.jwt_block_list = fake_jwt_block_list

print()
print("=== 2. user_refresh（刷新令牌） ===")


async def t_refresh():
    redis = FakeRedis()
    fuse = CircuitBreaker(name="redis")
    good = make_token("refresh", subject=str(USER_ID), session_id=str(SESSION_ID), jti="old-jti")
    out = await svc.user_refresh(good, redis, fuse, object())
    check("合法 refresh -> 返回新令牌对", set(out) == {"access_token", "refresh_token"}, str(list(out)))
    new_payload = decode_token(out["access_token"], jwt_key="x" * 40)
    check("新 access 令牌的 type/subject 正确",
          new_payload.token_type == "access" and new_payload.subject == str(USER_ID),
          f"type={new_payload.token_type} sub={new_payload.subject[:8]}...")
    check("旧 refresh 的 jti 被拉黑", redis.blocked == ["old-jti"], str(redis.blocked))

    expired = make_token("refresh", subject=str(USER_ID), session_id=str(SESSION_ID), delta=timedelta(seconds=-10))
    try:
        await svc.user_refresh(expired, FakeRedis(), CircuitBreaker(name="redis"), object())
        check("过期 refresh -> 401", False, "没有抛异常")
    except Exception as e:  # noqa: BLE001
        code = getattr(e, "status_code", None)
        check("过期 refresh -> 401（改前是 500）", code == 401, f"{type(e).__name__} status={code}")

    access = make_token("access", subject=str(USER_ID), session_id=str(SESSION_ID))
    try:
        await svc.user_refresh(access, FakeRedis(), CircuitBreaker(name="redis"), object())
        check("拿 access 当 refresh -> 401", False, "没有抛异常")
    except Exception as e:  # noqa: BLE001
        code = getattr(e, "status_code", None)
        check("拿 access 当 refresh -> 401", code == 401, f"{type(e).__name__} status={code}")

    ghost = make_token("refresh", subject=str(uuid.uuid4()), session_id=str(SESSION_ID))
    try:
        await svc.user_refresh(ghost, FakeRedis(), CircuitBreaker(name="redis"), object())
        check("用户已不存在 -> 401", False, "没有抛异常")
    except Exception as e:  # noqa: BLE001
        code = getattr(e, "status_code", None)
        check("用户已不存在 -> 401", code == 401, f"{type(e).__name__} status={code}")


asyncio.run(t_refresh())


# ----------------------------------------------------------------------
# user_logout：过期令牌也必须"登出成功"
# ----------------------------------------------------------------------
async def fake_clear_session(redis, user_id):
    return None


svc.clear_session = fake_clear_session

print()
print("=== 3. user_logout（登出） ===")


async def t_logout():
    redis = FakeRedis()
    fuse = CircuitBreaker(name="redis")
    access = make_token("access", subject=str(USER_ID), session_id=str(SESSION_ID), jti="a1")
    refresh = make_token("refresh", subject=str(USER_ID), session_id=str(SESSION_ID), jti="r1")
    out = await svc.user_logout(access_token=access, refresh_token=refresh, redis=redis, fuse=fuse)
    check("正常登出 -> success 且两个 jti 都被拉黑", out == {"success": True} and set(redis.blocked) == {"a1", "r1"}, str(redis.blocked))

    redis2 = FakeRedis()
    expired_access = make_token("access", subject=str(USER_ID), session_id=str(SESSION_ID), delta=timedelta(seconds=-10))
    out2 = await svc.user_logout(access_token=expired_access, refresh_token=refresh, redis=redis2, fuse=fuse)
    check("access 已过期仍登出成功（语义不变）", out2 == {"success": True}, str(out2))

    redis3 = FakeRedis()
    out3 = await svc.user_logout(access_token="garbage", refresh_token="garbage", redis=redis3, fuse=fuse)
    check("两个令牌都是垃圾仍登出成功", out3 == {"success": True}, str(out3))

    # 归属校验：access/refresh 属于不同用户 -> 401
    other = make_token("refresh", subject=str(uuid.uuid4()), session_id=str(SESSION_ID))
    try:
        await svc.user_logout(access_token=access, refresh_token=other, redis=FakeRedis(), fuse=fuse)
        check("两个令牌不同用户 -> 401", False, "没有抛异常")
    except Exception as e:  # noqa: BLE001
        code = getattr(e, "status_code", None)
        check("两个令牌不同用户 -> 401", code == 401, f"{type(e).__name__} status={code}")


asyncio.run(t_logout())

print()
bad = [r for r in results if not r[1]]
print(f"RESULT: {len(results) - len(bad)}/{len(results)} PASS" + ("" if not bad else "  FAILED: " + "; ".join(r[0] for r in bad)))
sys.exit(1 if bad else 0)

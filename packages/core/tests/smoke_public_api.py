# -*- coding: utf-8 -*-
"""furina-core 的**公开 API 冒烟测试** —— 也就是 README.md 的可执行版本。

# ── AI-ASSISTED ── 本文件由 AI 生成，待人工复核 ──
# 复核重点：
#   1. 它存在的理由：本仓库栽过"文档说已验证、树里跑不起来"的坑。
#      所以 packages/core/README.md 里写的每一条契约，这里都有一条断言。
#      **改了 README 就要同步这里**，反之亦然。
#   2. 断言只覆盖"契约"（参数校验、异常类型、返回值形状、状态迁移），
#      不覆盖业务正确性 —— core 没有业务。
#   3. 它**不打网络、不连数据库、不需要 Redis**；`config`/`security` 那部分靠临时改环境变量。
#      因此它可以在任何机器上跑，适合放进 CI 或提交前手动跑。
#   4. 与 `scripts/verify_core.py` 的分工：那边测熔断器/令牌桶的**并发行为**，
#      这边测**全部模块的对外契约**（含 enums/config/security/errors/models/
#      storage/checkpoint/sandbox/circuit_policies 这些那边完全没覆盖的）。

用法（在仓库根）：

    $env:PYTHONPATH = "packages\\core\\src"
    .venv-build\\Scripts\\python.exe packages\\core\\tests\\smoke_public_api.py
"""
import asyncio
import json
import os
import re
import sys
import time
from datetime import timedelta
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

RESULTS: list[tuple[str, bool, str]] = []


def check(label: str, cond: bool, extra: str = "") -> None:
    RESULTS.append((label, cond, extra))
    print(f"  [{'PASS' if cond else 'FAIL'}] {label:<54} {extra}")


def raises(exc_type, fn, *args, **kwargs):
    """返回 (是否抛出指定异常, 异常实例)。"""
    try:
        fn(*args, **kwargs)
        return False, None
    except exc_type as e:
        return True, e
    except Exception as e:  # noqa: BLE001
        return False, e


async def a_raises(exc_type, coro):
    """协程版 raises —— **在事件循环里不要用 asyncio.run**（会 RuntimeError）。"""
    try:
        await coro
        return False, None
    except exc_type as e:
        return True, e
    except Exception as e:  # noqa: BLE001
        return False, e


# ======================================================================
# 0. 包根零副作用（红线三）
# ======================================================================
print("=== 0. 包根零副作用 ===")
import furina_core  # noqa: E402

heavy = [m for m in ("bcrypt", "jwt", "sqlmodel", "fastapi", "openai", "dotenv") if m in sys.modules]
check("import furina_core 不加载任何子模块依赖", heavy == [], f"泄漏={heavy or '无'}")
check("包根只导出 __version__", furina_core.__all__ == ["__version__"], str(furina_core.__all__))

# 红线一/二 的**静态**检查（README §2 里那两条 grep 的可执行版本）
_CORE_SRC = Path(__file__).resolve().parents[1] / "src" / "furina_core"
_BANNED = {"asyncpg", "psycopg", "redis", "lancedb", "furina_web", "furina_desktop"}
_IMPORT_RE = re.compile(r"^(?:from|import)\s+([A-Za-z_][\w.]*)", re.M)
_violations = []
for _py in sorted(_CORE_SRC.rglob("*.py")):
    for _mod in _IMPORT_RE.findall(_py.read_text(encoding="utf-8")):
        if _mod.split(".")[0] in _BANNED:
            _violations.append(f"{_py.name}: {_mod}")
check("红线一/二：core 不 import 存储后端、也不 import app 包",
      _violations == [], str(_violations[:3]))

# ======================================================================
# 1. enums
# ======================================================================
print("=== 1. furina_core.enums ===")
from furina_core.enums import MessageRole  # noqa: E402

check("三个角色值", [m.value for m in MessageRole] == ["user", "assistant", "system"])
check("是 str 子类（json.dumps 可直接序列化）",
      json.dumps({"role": MessageRole.USER}) == '{"role": "user"}')
check("与字符串相等", MessageRole.USER == "user")

# ======================================================================
# 2. config
# ======================================================================
print("=== 2. furina_core.config ===")
from furina_core.config import CommonSettings, make_async_client, settings  # noqa: E402

check("全局 settings 是 CommonSettings 实例", isinstance(settings, CommonSettings))
for field in ("base_url", "api_key", "model", "search_api_key", "sandbox_root", "log_level", "log_dir"):
    check(f"字段 {field} 存在", hasattr(settings, field))
check("repr 不回显密钥", "api_key=" in repr(settings) and "sk-" not in repr(settings))

_saved_key = os.environ.pop("DEEPSEEK_API_KEY", None)
try:
    ok, err = raises(RuntimeError, CommonSettings().require_api_key)
    check("require_api_key 缺失时抛 RuntimeError", ok, type(err).__name__ if err else "")
finally:
    if _saved_key:
        os.environ["DEEPSEEK_API_KEY"] = _saved_key


async def _client_roundtrip():
    client = make_async_client()          # 不联网，只构造
    await client.close()                  # 契约：调用方负责关闭
    return type(client).__name__


check("make_async_client() 可构造且可 close", asyncio.run(_client_roundtrip()) == "AsyncOpenAI")

# ======================================================================
# 3. security
# ======================================================================
print("=== 3. furina_core.security ===")
from furina_core.security import (  # noqa: E402
    TokenError,
    TokenPayload,
    create_access_token,
    create_refresh_token,
    create_token,
    decode_token,
    decode_token_compat,
    hash_password,
    require_token_type,
    verify_password,
)

KEY = "unit-test-key-must-be-at-least-32-bytes!!"
OTHER_KEY = "another-key-that-is-also-long-enough-32b!!"
h = hash_password("pw")
check("hash_password 输出 bcrypt 串（60 字符、$2b$ 前缀）", h.startswith("$2b$") and len(h) == 60, h[:7])
check("verify_password 正确/错误口令", verify_password("pw", h) and not verify_password("no", h))
check("verify_password 遇到脏哈希返回 False（不抛）", verify_password("pw", "not-a-hash") is False)

tok = create_token(subject="u-1", token_type="access", jwt_key=KEY,
                   expires_delta=timedelta(seconds=60), session_id=None)
p = decode_token(tok, jwt_key=KEY)
check("create_token/decode_token 往返", isinstance(p, TokenPayload) and p.subject == "u-1")
check("token_type / jti / session_id", p.token_type == "access" and bool(p.jti) and p.session_id is None)
check("载荷同时含 sub 与 id（旧契约）", p.raw["sub"] == p.raw["id"] == "u-1", str(sorted(p.raw)))
check("remaining_seconds ≈ 60", 55 <= p.remaining_seconds <= 60, str(p.remaining_seconds))
check("TokenPayload 是 frozen（不可改）", raises(Exception, setattr, p, "subject", "x")[0])

# extra_claims 是**无过滤**的 update：能覆盖 sub/exp 等标准声明（安全相关，必须在文档里写明）
overridden = create_token(subject="u-real", token_type="access", jwt_key=KEY,
                          expires_delta=timedelta(seconds=60),
                          extra_claims={"sub": "u-fake", "exp": int(time.time()) + 600})
op = decode_token(overridden, jwt_key=KEY)
check("extra_claims 会覆盖同名标准声明（含 sub/exp）",
      op.subject == "u-fake" and op.remaining_seconds > 300,
      f"subject={op.subject} remaining={op.remaining_seconds}")

ok, err = raises(TokenError, decode_token, tok, jwt_key=OTHER_KEY)
check("错误密钥 -> TokenError(kind=invalid)", ok and err.kind == "invalid")
expired = create_token(subject="u", token_type="access", jwt_key=KEY, expires_delta=timedelta(seconds=-5))
ok, err = raises(TokenError, decode_token, expired, jwt_key=KEY)
check("过期 -> TokenError(kind=expired)", ok and err.kind == "expired")
check("require_token_type 不符 -> TokenError", raises(TokenError, require_token_type, p, "refresh")[0])
check("require_token_type 相符不抛", raises(TokenError, require_token_type, p, "access")[0] is False)
check("decode_token 自己**不**检查 type（必须显式调 require_token_type）",
      decode_token(create_token(subject="u", token_type="refresh", jwt_key=KEY,
                                expires_delta=timedelta(seconds=60)), jwt_key=KEY).token_type == "refresh")

# 兼容垫片：密钥从环境变量读；缺失时是 RuntimeError（配置错误，不是令牌错误）
os.environ.pop("JWT_SECRET_KEY", None)
ok, err = raises(RuntimeError, create_access_token, "u-1", "name", None)
check("垫片缺 JWT_SECRET_KEY -> RuntimeError", ok, type(err).__name__ if err else "")
ok, err = raises(RuntimeError, decode_token_compat, tok)
check("decode_token_compat 缺密钥 -> RuntimeError", ok, type(err).__name__ if err else "")

os.environ["JWT_SECRET_KEY"] = KEY
a = decode_token(create_access_token("u-1", "name", None), jwt_key=KEY)
r = decode_token(create_refresh_token("u-1", "name", None), jwt_key=KEY)
check("垫片 access=3600s / refresh=30d",
      3500 <= a.remaining_seconds <= 3600 and 2_590_000 <= r.remaining_seconds <= 2_592_000,
      f"access={a.remaining_seconds}s refresh={r.remaining_seconds}s")
check("垫片不写 name（刻意）", "name" not in a.raw, str(sorted(a.raw)))

# ======================================================================
# 4. errors
# ======================================================================
print("=== 4. furina_core.errors ===")
from furina_core.errors import (  # noqa: E402
    AgentError,
    InvalidArgumentError,
    InvalidToolError,
    MissingRequiredArgumentError,
    MissingRequiredToolError,
)

for exc, kwargs in [
    (InvalidToolError, {"invalid_tools": ["a", "b"]}),
    (InvalidToolError, {"invalid_tools": "a"}),
    (MissingRequiredToolError, {"missing_tools": ["a", "b"]}),
    (MissingRequiredArgumentError, {"missing_args": ["a"], "missing_args_tools": ["t"]}),
    (MissingRequiredArgumentError, {"missing_args": ["a"], "missing_args_tools": "t"}),
    (MissingRequiredArgumentError, {"missing_args": "a", "missing_args_tools": "t"}),
    (InvalidArgumentError, {"invalid_args": ["a"], "invalid_args_tools": ["t"]}),
    (InvalidArgumentError, {"invalid_args": "a", "invalid_args_tools": "t"}),
]:
    e = exc(**kwargs)
    check(f"{exc.__name__}[{'+'.join(kwargs)}] str(e)/args/message 都非空",
          bool(str(e)) and bool(e.args) and isinstance(e.message, str), f"{str(e)[:30]!r}")

check("业务字段原样保存在实例上", InvalidToolError(invalid_tools=["x"]).invalid_tools == ["x"])
check("code 是类属性", InvalidToolError.code == "INVALID_TOOL" and issubclass(InvalidToolError, AgentError))
check("message 参数可覆盖默认文案（四个子类都生效）",
      str(AgentError("自定义")) == "自定义"
      and str(InvalidToolError(invalid_tools=["x"], message="自定义")) == "自定义"
      and str(MissingRequiredToolError(missing_tools=["x"], message="自定义")) == "自定义"
      and str(MissingRequiredArgumentError(missing_args=["a"], missing_args_tools="t", message="自定义")) == "自定义"
      and str(InvalidArgumentError(invalid_args=["a"], invalid_args_tools="t", message="自定义")) == "自定义",
      str(InvalidArgumentError(invalid_args=["a"], invalid_args_tools="t", message="自定义")) == "自定义")

# ======================================================================
# 5. models
# ======================================================================
print("=== 5. furina_core.models ===")
from furina_core.models import AgentThreadID, User, get_datetime_utc  # noqa: E402

check("get_datetime_utc 是带时区的 UTC", get_datetime_utc().tzinfo is not None)
check("User 表名", User.__tablename__ == "user", User.__tablename__)
check("User 列齐备",
      set(User.__table__.columns.keys()) == {"id", "user_name", "created_at", "updated_at",
                                             "hashed_password", "personal_preference"},
      str(sorted(User.__table__.columns.keys())))
check("User 没有 conversations 关系（core 不认识 web 的表）",
      "conversations" not in User.__mapper__.relationships)
check("AgentThreadID 外键指向 user.id",
      [fk.target_fullname for fk in AgentThreadID.__table__.foreign_keys] == ["user.id"])

# ======================================================================
# 6. storage.session
# ======================================================================
print("=== 6. furina_core.storage.session ===")
from furina_core.storage import get_session  # noqa: E402


class _FakeSessionMaker:
    def __call__(self):
        return self

    async def __aenter__(self):
        return "SESSION-OBJ"

    async def __aexit__(self, *exc):
        return False


class _FakeRequest:
    class app:
        class state:
            async_session = _FakeSessionMaker()


class _NoFactoryRequest:
    class app:
        class state:
            pass


async def _session_dep(request):
    agen = get_session(request)
    return await agen.__anext__()


check("从 request.app.state.async_session 取会话",
      asyncio.run(_session_dep(_FakeRequest())) == "SESSION-OBJ")
ok, err = raises(AttributeError, asyncio.run, _session_dep(_NoFactoryRequest()))
check("app.state 没挂工厂 -> AttributeError（请求期，不是启动期）", ok, type(err).__name__ if err else "")

# ======================================================================
# 7. checkpoint（协议）
# ======================================================================
print("=== 7. furina_core.checkpoint ===")
from furina_core.checkpoint import CheckpointStore  # noqa: E402

MEMBERS = ["setup", "close", "aget_tuple", "alist", "aput", "aput_writes", "adelete_thread"]
check("协议声明了 7 个成员", all(hasattr(CheckpointStore, m) for m in MEMBERS), str(MEMBERS))


class _SyncFake:
    """**故意全同步** —— 用来证明协议不做签名检查。"""

    def setup(self): ...
    def close(self): ...
    def aget_tuple(self, config): ...
    def alist(self, config, *, filter=None, before=None, limit=None): ...
    def aput(self, config, checkpoint, metadata, new_versions): ...
    def aput_writes(self, config, writes, task_id, task_path=""): ...
    def adelete_thread(self, thread_id): ...


class _Empty:
    pass


check("全同步的假类 isinstance -> True（只查属性名）", isinstance(_SyncFake(), CheckpointStore) is True)
check("空类 isinstance -> False", isinstance(_Empty(), CheckpointStore) is False)

# ======================================================================
# 8. sandbox
# ======================================================================
print("=== 8. furina_core.sandbox ===")
from furina_core.sandbox import PathJail, PathOutOfSandbox  # noqa: E402

jail = PathJail("sandbox")
check("root 是解析后的绝对路径", jail.root.is_absolute(), str(jail.root))
check("沙箱内相对路径 -> 绝对路径", jail.resolve("a/b.txt") == (jail.root / "a" / "b.txt"))
for bad in ("", "   ", None):
    check(f"空值 {bad!r} -> ValueError", raises(ValueError, jail.resolve, bad)[0])
check("绝对路径 -> ValueError", raises(ValueError, jail.resolve, str(jail.root / "x.txt"))[0])
ok, err = raises(PathOutOfSandbox, jail.resolve, "../../etc/passwd")
check("越界 -> PathOutOfSandbox", ok)
check("越界异常消息不含真实路径", "etc" not in str(err), str(err))
check("越界真路径留在 .target（给日志）", "etc" in str(err.target), str(err.target))
check("is_inside 不抛异常", jail.is_inside("ok.txt") is True and jail.is_inside("../x") is False)

# ======================================================================
# 9. circuit_breaker + circuit_policies
# ======================================================================
print("=== 9. furina_core.circuit_breaker / circuit_policies ===")
from furina_core.circuit_breaker import CircuitBreaker, CircuitOpenError  # noqa: E402
from furina_core.circuit_policies import fail_closed, fail_open  # noqa: E402


async def _downstream_boom():
    raise ValueError("下游炸了")


async def _downstream_ok():
    return "OK"


async def _fail_open_with_kwargs():
    # 关键字会被拒（签名里只有 action 是关键字参数）—— 在调用时就 TypeError
    return await fail_open(CircuitBreaker(name="p"), _downstream_ok, "D", x=1)


async def _fail_closed_boom():
    return await fail_closed(CircuitBreaker(name="p"), _downstream_boom)


async def _breaker_flow():
    out = {"kwargs_only": raises(TypeError, CircuitBreaker, object())[0]}
    br = CircuitBreaker(name="t", fail_threshold=2, cooldown_seconds=0.2,
                        probe_success=1, probe_failure=1)
    check("构造是关键字专用（位置参数 -> TypeError）", out["kwargs_only"] is True)

    for _ in range(2):
        await asyncio.gather(br(_downstream_boom), return_exceptions=True)
    check("连续失败达阈值 -> OPEN", br.state == "OPEN", br.state)

    ok, err = await a_raises(CircuitOpenError, br(_downstream_ok))
    check("OPEN 期间短路，抛 CircuitOpenError 且不调下游", ok, type(err).__name__ if err else "")
    check("snapshot 字段固定", sorted(br.snapshot()) ==
          sorted(["name", "state", "fail_count", "probe_ok", "probe_fail", "opened_at"]))

    await asyncio.sleep(0.25)
    check("冷却后放行探测 -> 成功即 CLOSE",
          await br(_downstream_ok) == "OK" and br.state == "CLOSE", br.state)
    br.reset()
    check("reset() 手动复归", br.state == "CLOSE")

    check("fail_open 下游报错 -> 返回 default",
          await fail_open(CircuitBreaker(name="p"), _downstream_boom, "DEFAULT") == "DEFAULT")
    check("fail_closed 下游报错 -> 原样抛", (await a_raises(ValueError, _fail_closed_boom()))[0])
    check("两个策略都不透传 kwargs（TypeError）",
          (await a_raises(TypeError, _fail_open_with_kwargs()))[0])
    return out


asyncio.run(_breaker_flow())

# ======================================================================
# 10. limits
# ======================================================================
print("=== 10. furina_core.limits ===")
from furina_core.limits import LocalTokenBucket, RateLimitExceeded  # noqa: E402

check("capacity<=0 -> ValueError", raises(ValueError, LocalTokenBucket, capacity=0, refill_rate=1.0)[0])
check("refill_rate<=0 -> ValueError", raises(ValueError, LocalTokenBucket, capacity=1, refill_rate=0)[0])
check("构造是关键字专用", raises(TypeError, LocalTokenBucket, 5, 1.0)[0])
check("initial_tokens=0 -> 桶是空的",
      LocalTokenBucket(capacity=2, refill_rate=1.0, initial_tokens=0).snapshot()["tokens"] == 0.0)
check("snapshot 字段固定",
      sorted(LocalTokenBucket(capacity=1, refill_rate=1.0).snapshot()) ==
      sorted(["key", "tokens", "capacity", "refill_rate", "idle_seconds"]))


async def _bucket_flow():
    b = LocalTokenBucket(capacity=1, refill_rate=0.05, key="t")
    check("拿完就 False（不抛）", await b.try_acquire() is True and await b.try_acquire() is False)
    check("tokens>capacity -> ValueError（不死等）", (await a_raises(ValueError, b.try_acquire(5)))[0])
    check("tokens<=0 -> ValueError", (await a_raises(ValueError, b.try_acquire(0)))[0])

    t0 = time.monotonic()
    ok, err = False, None
    try:
        await b.acquire(timeout=0.1)
    except RateLimitExceeded as e:
        ok, err = True, e
    elapsed = round(time.monotonic() - t0, 2)
    check("acquire 超时 -> RateLimitExceeded(key, retry_after)",
          ok and err.key == "t" and isinstance(err.retry_after, float), f"{err!r}"[:70])
    check("超时在 timeout 附近返回（≤0.4s）", elapsed <= 0.4, f"{elapsed}s")

    b.reset()
    check("reset() 填满；__call__ 等价 try_acquire",
          await b.try_acquire() is True and await b() is False)


asyncio.run(_bucket_flow())

# ======================================================================
bad = [r for r in RESULTS if not r[1]]
print()
print(f"RESULT: {len(RESULTS) - len(bad)}/{len(RESULTS)} PASS"
      + ("" if not bad else "  FAILED: " + "; ".join(r[0] for r in bad)))
sys.exit(1 if bad else 0)

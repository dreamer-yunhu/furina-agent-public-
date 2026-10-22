# furina-core · 对外 API 说明书

> **这个库是干什么的**：web 与 desktop **共用**的**无业务内核** —— 配置、共享枚举与表模型、
> 认证原语（bcrypt + JWT）、熔断器与降级策略、路径边界、进程内限流、agent 状态持久化协议。
> 它**不**连数据库、**不**认识 HTTP 状态码、**不**含任何业务逻辑。
>
> **怎么读（黑盒使用者）**：§1 看它有什么 → §2 导入规则 → §3 契约与硬规则（**读完这节就能安全用**）
> → §4 查具体 API 的参数。§5 之后是边界、限制、自检等杂项。
>
> **可信度声明**：下面每一条契约在 `packages/core/tests/smoke_public_api.py` 里都有**可执行断言**
> （当前 86 项全绿）。文档与脚本冲突时**以脚本为准** —— 这是本仓库吃过"文档说已验证、
> 树里跑不起来"的教训之后定下的规矩。
>
> 本文件由 AI 生成，待人工复核。**复核重点：§6「已知限制」里哪几条与你现在的产品意图冲突。**
> 状态：Python 3.12 / `.venv-build`，本轮修复会话实测。

---

## 一、这个库是干什么的：模块与用途总览

| 模块 | 用途 | 典型场景 | 对外符号 |
|---|---|---|---|
| `furina_core.config` | 两边共用的配置读取 + LLM 客户端工厂 | 读 `DEEPSEEK_API_KEY` / 沙箱根；造 `AsyncOpenAI` | `settings`、`CommonSettings`、`make_async_client` |
| `furina_core.enums` | 跨产品共享枚举 | 消息角色（存库 / 出接口） | `MessageRole` |
| `furina_core.errors` | 通用校验错误 | 模型幻觉工具名/参数、缺必填参数 | `AgentError` + 4 个子类 |
| `furina_core.models` | 共享表模型（**只有两张**） | web 存 PG、desktop 存 SQLite，表结构共享 | `User`、`AgentThreadID`、`get_datetime_utc` |
| `furina_core.security` | 口令哈希 + JWT 原语 | 注册/登录/鉴权/登出/刷新 | `hash_password`、`verify_password`、`create_token`、`decode_token`、`require_token_type`、`TokenPayload`、`TokenError`（+3 个兼容垫片） |
| `furina_core.storage` | FastAPI 会话依赖 | 每个请求一个 `AsyncSession` | `get_session` |
| `furina_core.checkpoint` | agent 状态持久化**协议** | web 用 PG、desktop 用 SQLite 各自实现 | `CheckpointStore` |
| `furina_core.circuit_breaker` | 三态熔断器 | 保护 Redis / LLM 等下游 | `CircuitBreaker`、`CircuitOpenError` |
| `furina_core.circuit_policies` | 两种降级策略 | 决定"打不通之后怎么办" | `fail_open`、`fail_closed` |
| `furina_core.sandbox` | 路径越界守卫 | 模型给的文件路径不许跑出沙箱 | `PathJail`、`PathOutOfSandbox` |
| `furina_core.limits` | 进程内令牌桶限流 | 限出站 LLM 调用（防成本失控） | `LocalTokenBucket`、`RateLimiter`、`RateLimitExceeded` |

**它明确不做的事**（不要指望）：

- 不含任何存储后端：没有 PG / Redis / SQLite 客户端，也没有建表逻辑 → 见 §5 红线一；
- 不决定 HTTP 状态码：异常抛给你，由你映射（映射表见 §3.2）；
- 不含业务：没有对话、用户、权限逻辑，只有原语与协议。

> ⚠️ 两处"已实现但本仓库尚未接线"：`sandbox.PathJail` 与 `limits.LocalTokenBucket`
> 目前在仓库内**没有调用者**（desktop 工具层自己复制了一份路径检查）。见 §6 第 12 条。

---

## 二、导入规则

### 2.1 一律显式导入子模块

```python
from furina_core.security import hash_password          # ✅ 正确
from furina_core.limits import LocalTokenBucket         # ✅ 正确
from furina_core import LocalTokenBucket                # ❌ 不行：包根不导出任何子模块
```

包根 `furina_core/__init__.py` **刻意不 import 任何子模块**（红线三）。因此：

| 规则 | 说明 |
|---|---|
| `import furina_core` | 合法，但只有 `__version__`；不会顺带加载 fastapi/bcrypt/sqlmodel |
| `furina_core.__all__` | 只有 `["__version__"]` |
| 少数子包有再导出 | `furina_core.limits` 导出 `LocalTokenBucket`/`RateLimiter`/`RateLimitExceeded`；`furina_core.storage` 导出 `get_session`。其余请从**模块**导入 |

**为什么值得这样用**：desktop 只用到 `limits` 时，不必因为一次 import 就把 `bcrypt`、
`fastapi`、`sqlmodel` 全部拖进内存（实测：`import furina_core` 后这些模块都不在 `sys.modules`）。

### 2.2 依赖方向

`app → core` 单向。core 里**不会** import `furina_web` / `furina_desktop`，
也不会 import 任何具体存储后端（`asyncpg`/`psycopg`/`redis`/`lancedb`）。这两条就是 §5 的红线一、二。

---

## 三、对外契约与硬规则

### 3.1 六条硬规则（违反了就会踩坑，都是实测出来的）

| # | 规则 | 违反的后果 |
|---|---|---|
| 1 | **显式子模块导入**（见 §2.1） | 包根拿不到符号；或无意中加载一堆用不到的依赖 |
| 2 | 构造器**关键字专用**：`CircuitBreaker(name=...)`、`LocalTokenBucket(capacity=...)`、`create_token(subject=...)` | 传位置参数 → `TypeError`（故意设计，防参数错位） |
| 3 | 令牌解码返回**对象**（`TokenPayload`）不是 dict：写 `payload.subject`，**不要** `payload.get("sub")` | 漏改会在**运行期**抛 `AttributeError`（import 和启动全都正常，只有请求进来才炸） |
| 4 | 异常要**自己映射**成状态码（见 §3.2） | 忘了映射 `TokenError` → 令牌过期变成 **500**（应为 401） |
| 5 | core 里**没有**数据库/Redis：需要连的地方自己写；core 只给协议和类型 | 找不到 `init_db` 之类的东西，别以为漏装了 |
| 6 | 加表模型时：**不要写跨包关系**；两个互相引用的类**不要**加 `from __future__ import annotations` | 任何真实 ORM 查询在 `configure_mappers` 阶段炸（web + desktop 双双中招），详见 §4.4 |

### 3.2 异常 → 你的响应（状态码映射表）

core 只负责抛，怎么回给客户端是你的决定。**推荐映射**：

| core 抛出的 | 含义 | 典型响应 |
|---|---|---|
| `TokenError(kind="expired")` | 令牌过期 | 401，提示重新登录 |
| `TokenError(kind="invalid")` | 签名不对 / 缺主体 / 类型不符 | 401（`require_token_type` 失败也走这个） |
| `RuntimeError`（`require_api_key()`、`require_*_url()`、垫片缺 `JWT_SECRET_KEY`） | **配置缺失**，不是用户的问题 | 500 + 明确日志（**不要**当 401） |
| `CircuitOpenError` | 熔断中，**压根没打下游** | 503 + `Retry-After`，或按 `fail_open` 降级 |
| 下游原始异常（熔断器**不吞**） | 真调了下游，下游报错 | 按业务决定：重试 / 降级 / 5xx |
| `RateLimitExceeded(key, retry_after)` | 令牌桶配额不足且要求不等待 | 429，`Retry-After: retry_after` |
| `PathOutOfSandbox` | 路径越界 | 拒绝该工具调用；`str(e)` 已脱敏，可直接回给模型 |
| `ValueError`（`PathJail` 空/绝对路径、`LocalTokenBucket` 参数非法） | 入参非法 | 400 或工具错误 |
| `AgentError` 子类 | 模型幻觉工具/参数、缺必填参数 | 工具错误回填给模型（带 `code` 分类） |

### 3.3 参数传递规则（一张表记住）

| 调用形状 | 例子 | 说明 |
|---|---|---|
| **全关键字、位置参数会报错** | `CircuitBreaker(name=...)`、`LocalTokenBucket(capacity=..., refill_rate=...)`、`create_token(*, subject=..., jwt_key=..., expires_delta=...)` | `expires_delta` 等没有默认值的必须给 |
| **只透传位置参数** | `await fail_open(breaker, fn, default, *args, action="…")`、`await fail_closed(breaker, fn, *args, action="…")` | 签名里没有 `**kwargs`：给 `fn` 传关键字直接 `TypeError`（**不会**静默丢弃） |
| **args/kwargs 都透传** | `await breaker(fn, *args, **kwargs)` | 返回值就是 `fn` 的返回值 |
| **看第一个参数类型分叉** | `errors` 的四个子类：传 `list` → 每条一句；传 `str` → 合成一句 | 两个参数类型不一致时走合成分支 |
| **依赖注入** | `get_session`、`CheckpointStore`（协议，结构化类型不用继承） | `get_session` 从 `request.app.state.async_session` 取工厂 |

---

## 四、API 参考：用途 · 参数 · 契约

### 4.1 `furina_core.config`

**用途**：两边共用的配置读取 + LLM 客户端工厂。**不含** web 私有的 `pg_url`/`redis_url`/`jwt_*`
（那些在 `furina_web.config.WebSettings(CommonSettings)`）。

```python
from furina_core.config import CommonSettings, make_async_client, settings
```

| 符号 | 签名 | 参数 / 返回 |
|---|---|---|
| `settings` | `CommonSettings` 实例 | **模块导入时构造一次**；之后改环境变量不再生效 |
| `CommonSettings()` | 无参 | 字段见下表 |
| `settings.require_api_key()` | `() -> str` | 缺失抛 `RuntimeError`（**不在导入期抛**：不用 LLM 的人也能启动） |
| `settings.require_search_key()` | `() -> str` | 同上，只给联网搜索工具用 |
| `make_async_client()` | `() -> AsyncOpenAI` | 每次调用造一个客户端；**调用方负责 `await client.close()`** |

| 字段 | 环境变量 | 默认值 | 类型 |
|---|---|---|---|
| `base_url` | `LLM_BASE_URL` | `https://api.deepseek.com/v1` | `str` |
| `api_key` | `DEEPSEEK_API_KEY` | `None` | `str \| None` |
| `model` | `LLM_MODEL` | `deepseek-v4-flash` | `str` |
| `search_api_key` | `BOCHA_SEARCH_API_KEY` | `None` | `str \| None` |
| `sandbox_root` | `SANDBOX_ROOT` | `Path(".")` ⚠️ | `Path` |
| `log_level` | `LOG_LEVEL` | `INFO` | `str` |
| `log_dir` | `LOG_DIR` | `logs`（相对 CWD） | `Path` |

**契约**：导入本模块会读一次 `.env`（从本文件所在目录向上最多 5 层，`override=False`）；
`repr(settings)` 刻意不回显 api_key；子类化是官方用法，两边的 `settings` 是**两个对象**。

### 4.2 `furina_core.enums`

**用途**：跨产品共享枚举。**参数**：无。

```python
from furina_core.enums import MessageRole   # USER="user" / ASSISTANT / SYSTEM
```

`MessageRole` 继承 `str`：`json.dumps({"role": MessageRole.USER})` 直接可用；入库请存 `.value`。
本模块不 import 任何东西（依赖图的叶子）。

### 4.3 `furina_core.errors`

**用途**：模型"幻觉工具名 / 幻觉参数 / 缺参数"这类通用校验错误。

```python
from furina_core.errors import (
    AgentError,                    # 基类：code="AGENT_ERROR"
    MissingRequiredToolError,      # code="MISSING_REQUIRED_TOOL"
    InvalidToolError,              # code="INVALID_TOOL"
    MissingRequiredArgumentError,  # code="MISSING_REQUIRED_ARGUMENT"
    InvalidArgumentError,          # code="INVALID_ARGUMENT"
)
```

| 类 | 参数（都可用关键字传） |
|---|---|
| `AgentError` | `message=None` |
| `MissingRequiredToolError` | `missing_tools: list[str] \| str`, `message=None` |
| `InvalidToolError` | `invalid_tools: list[str] \| str`, `message=None` |
| `MissingRequiredArgumentError` | `missing_args: list[str] \| str`, `missing_args_tools: list[str] \| str`, `message=None` |
| `InvalidArgumentError` | `invalid_args: list[str] \| str`, `invalid_args_tools: list[str] \| str`, `message=None` |

**契约**
- `str(e)`、`e.args[0]`、`e.message` **统一都是非空 `str`**；多条目之间用单个空格连接。
- 业务字段（`invalid_tools` / `missing_args` / …）**原样保存**传入值，不校验、不拷贝。
- 传 `list` 走"每条一句"，传 `str` 走"合成一句"；**分支只看第一个参数的类型**
  （两者类型不一致时走合成分支，列表会被原样打印，如 `缺少：['a']`）。
- `message` 传了就用它（其余参数仍保存在实例字段上）。`code` 是**类属性**，不参与 `args`。
- ⚠️ 已知外观瑕疵：默认文案自带中文冒号，模板又补一个 → `大模型幻觉工具：：a`（**双冒号**）。

### 4.4 `furina_core.models`

**用途**：两边共用的表模型 —— **只有这两张**。

```python
from furina_core.models import AgentThreadID, User, get_datetime_utc
```

| 表 | 列 | 约束 |
|---|---|---|
| `User` | `id` / `user_name` / `created_at` / `updated_at` / `hashed_password` / `personal_preference` | `id` uuid4 主键；`user_name` unique；`hashed_password` max_length=60（正好 bcrypt 长度）；时间列 `DateTime(timezone=True)`，默认 `get_datetime_utc`；`personal_preference` 为 `Text` 可空 |
| `AgentThreadID` | `id` / `created_at` / `updated_at` / `title` / `user_id` | `title` max 255；`user_id` 外键 `user.id`，`ON DELETE CASCADE`，有索引 |

`get_datetime_utc() -> datetime`：带时区的 UTC 时间戳工厂（时间比较别用本地时区）。

**契约（血泪版，务必遵守）**
1. **只放"两边都要"的表**。`Conversation` / `Message` 是 web 独有的，留在 `furina_web.models.table`。
2. **不要写跨包关系**。`User.conversations = Relationship(...)` 指向 web 的类名时，
   注解要在**定义它的模块**里解析，解析不到就把整串 `list['Conversation']` 交给 SQLAlchemy
   → **web 与 desktop 双方**的任何真实 ORM 查询都会在 `configure_mappers` 抛 `InvalidRequestError`。
3. **互相引用的两个类不要加 `from __future__ import annotations`**。加上以后注解全变字符串，
   pydantic 求值失败，同样是 `configure_mappers` 炸。正确姿势："注解写成字符串、类里不用未来注解"，
   由 SQLAlchemy 注册表按名字解析。
4. 验证脚本：`scripts/verify_models.py web|desktop`（必须**分进程**跑）。

### 4.5 `furina_core.security`

**用途**：口令哈希 + JWT 签发/校验。core **不抛 HTTPException**，状态码由调用方决定（§3.2）。

```python
from furina_core.security import (
    hash_password, verify_password,
    create_token, decode_token, require_token_type,
    TokenPayload, TokenError,
    create_access_token, create_refresh_token, decode_token_compat,  # 兼容垫片
)
```

| 符号 | 签名 | 参数要求 / 返回 / 异常 |
|---|---|---|
| `hash_password` | `(password: str) -> str` | bcrypt rounds=12，返回 60 字符 `$2b$` 串，可直接入库 |
| `verify_password` | `(plain_password: str, hashed_password: str) -> bool` | 哈希格式非法 → `False`，**不抛异常**（避免把 422 变 500） |
| `create_token` | `(*, subject: uuid.UUID \| str, token_type: "access"\|"refresh", jwt_key: str, algorithm="HS256", expires_delta: timedelta, session_id: uuid.UUID \| str \| None = None, extra_claims: dict \| None = None) -> str` | 全**关键字专用**；`expires_delta` **必填**；`jwt_key` 显式传 |
| `decode_token` | `(token: str, *, jwt_key: str, algorithm="HS256") -> TokenPayload` | 失败抛 `TokenError` |
| `require_token_type` | `(payload: TokenPayload, expected: "access"\|"refresh") -> None` | 类型不符抛 `TokenError`；`decode_token` **自己不做**这个检查 |
| `TokenError` | `(kind: "expired"\|"invalid", detail: str)` | 属性 `.kind` / `.detail` |
| `TokenPayload` | frozen dataclass | `.subject` / `.token_type` / `.jti` / `.session_id` / `.expires_at` / `.raw` / `.remaining_seconds` |

**载荷形状（外部契约，客户端解析时看得到）**

```
sub, id    —— 同一个值（id 是历史遗留的 refresh 契约；解码时 sub 优先）
type       —— "access" | "refresh"
jti        —— uuid4 字符串
iat, exp   —— 签发/过期时间
session_id —— 仅传了才出现（web 的"顶号"用；desktop 可以不传）
```

**契约与坑**
- 算 Redis 黑名单 TTL 用 **`payload.remaining_seconds`**（已 `max(0, …)`），别再手算 `exp - time.time()`。
- `extra_claims` 是**无过滤的 `dict.update`**：能覆盖 `sub` / `exp` / `type` 等标准声明
  （实测传 `{"sub": "u-fake"}` 会把主体换掉）—— 只传你确认安全的字段。
- 兼容垫片 `create_access_token(user_id, user_name, session_id)` / `create_refresh_token(...)` /
  `decode_token_compat(token)`：密钥从环境变量 `JWT_SECRET_KEY` / `JWT_ALGO` 读，
  TTL 写死 access=3600s、refresh=30d，**缺密钥抛 `RuntimeError`**；
  `user_name` **不写进载荷**（刻意：用户名应查库）。新代码请用 `create_token` / `decode_token`。

### 4.6 `furina_core.storage`

**用途**：FastAPI 的会话依赖。

```python
from furina_core.storage import get_session

@router.get("/x")
async def x(session: AsyncSession = Depends(get_session)): ...
```

**参数**：`get_session(request: Request)`，由 FastAPI 注入，你不用自己传。
**契约**：它**不创建**会话工厂，而是从 `request.app.state.async_session` 取。所以每个 app
必须在自己的 lifespan 里先挂：

```python
app.state.async_session = async_sessionmaker(bind=engine, expire_on_commit=False)
```

没挂 → `AttributeError` 发生在**第一个请求**（不是启动时），排障时注意这个时间差。

### 4.7 `furina_core.checkpoint`

**用途**：把"agent 状态存哪"从业务代码里隔离。业务层只依赖协议，装配层交出真 saver。

```python
from furina_core.checkpoint import CheckpointStore
```

**7 个成员**（结构化类型：**不需要继承**，方法名对得上即可；LangGraph 原生 saver 开箱满足）

| 成员 | 签名 | 契约 |
|---|---|---|
| `setup` | `async () -> None` | 建表/索引，**必须幂等** |
| `close` | `async () -> None` | 释放连接（不关 → PG 连接池泄漏；Windows 上 SQLite 锁文件） |
| `aget_tuple` | `async (config) -> Any \| None` | `config["configurable"]["thread_id"]` 必须有；不存在返回 `None` |
| `alist` | `(config, *, filter=None, before=None, limit=None) -> AsyncIterator` | 协议里是普通 `def` 返回异步迭代器；**实现处写 `async def` + `yield`** |
| `aput` | `async (config, checkpoint, metadata, new_versions) -> Any` | **返回值不能丢**（含新 `checkpoint_id`，`aput_writes` 要用） |
| `aput_writes` | `async (config, writes: Sequence[tuple[str, Any]], task_id: str, task_path: str = "") -> None` | 节点副作用记录；中断恢复靠它判断"哪些不用重跑" |
| `adelete_thread` | `async (thread_id: str) -> None` | 删**干净**该 thread 的全部检查点与写入；**必须幂等** |

**契约与坑**
- `@runtime_checkable` **只检查属性名存在**，不查签名、不查是不是 `async`：实测一个**全同步**的
  同名类 `isinstance(obj, CheckpointStore)` 也是 `True`。类型安全靠自觉（或装 mypy）。
- 上游 LangGraph 的 `aget`（`aget_tuple` 的包装）**不在本协议里**，不必实现。
- 本项目内的**装配约定**：适配器实现本协议，同时公开 `.saver` 属性指向真正的 LangGraph saver；
  装配层用 `getattr(obj, "saver", None)` 解包后 `compile(checkpointer=...)`
  —— 因为 LangGraph 的 `compile()` 会 `isinstance` 检查，只认 `BaseCheckpointSaver`。
  ⚠️ **`.saver` 这个名字不能改**：改名不报错，只会在很远的下游报 "Invalid checkpointer provided"。

### 4.8 `furina_core.circuit_breaker`

**用途**：下游（Redis / LLM）连续失败时快速失败，避免雪崩。

```python
from furina_core.circuit_breaker import CircuitBreaker, CircuitOpenError

breaker = CircuitBreaker(name="llm", fail_threshold=3, cooldown_seconds=10.0)
result = await breaker(call_llm, prompt, timeout=30)   # 透传 args/kwargs
```

| 符号 | 签名 | 参数要求 / 说明 |
|---|---|---|
| `CircuitBreaker` | `(*, name="downstream", fail_threshold=5, cooldown_seconds=10.0, probe_success=3, probe_failure=3)` | **关键字专用**；**一个实例 = 一条下游链路**（共用会互相误伤） |
| `await breaker(fn, *args, **kwargs) -> T` | `fn: Callable[..., Awaitable[T]]` | 返回值类型跟随 `fn`；下游异常**原样上抛** |
| `.state` | `"CLOSE"` / `"OPEN"` / `"HALF_OPEN"` | 运行期不校验字面量 |
| `.is_open` | `bool` | — |
| `.snapshot()` | `{name, state, fail_count, probe_ok, probe_fail, opened_at}` | 给 `/health` 或日志用（别去解析日志字符串判断状态） |
| `.reset()` | `None` | 手动复归 CLOSE（同步方法，无 await） |
| `CircuitOpenError` | 异常 | 语义是"**我没打下游**"，不是"下游坏了" |

**状态迁移**：`CLOSE --连续失败>=fail_threshold--> OPEN`（记 `opened_at`、计数归零）
→ `OPEN --冷却期满(下次调用时判定)--> HALF_OPEN` → `HALF_OPEN --成功>=probe_success--> CLOSE`
/ `--失败>=probe_failure--> OPEN`。

**契约与坑**：**绝不吞异常**（要不要重试/降级是调用方的事，用 §4.9）；
下游自己抛的 `CircuitOpenError`（嵌套熔断器）**不计为失败**（防自我强化）；
`HALF_OPEN` 期间**不限制并发探测数**（冷却一到，所有并发请求都会放行去探测）；
计数与迁移在 `asyncio.Lock` 内，下游调用在锁外（不串行化请求）。

### 4.9 `furina_core.circuit_policies`

**用途**：决定"打不通下游之后怎么办"。

```python
from furina_core.circuit_policies import fail_open, fail_closed

history   = await fail_open(breaker, get_hot_message, [], redis, conv_id, action="读热缓存")
is_banned = await fail_closed(breaker, is_blocklisted, redis, jti, action="门禁黑名单")
```

| 函数 | 签名 | 参数要求 / 行为 |
|---|---|---|
| `fail_open` | `async (breaker, fn, default: T, *args, action="下游调用") -> T` | 熔断**或**下游抛错 → 记日志并返回 `default`。用于"没有它也能活"的（缓存、检索、装饰数据） |
| `fail_closed` | `async (breaker, fn, *args, action="下游调用") -> T` | 熔断**或**下游抛错 → 记日志并**原样抛出**。用于"没有它就不能安全继续"的（鉴权黑名单、会话对账） |

**契约与坑**：给 `fn` 的参数**只能位置传**（签名没有 `**kwargs`，传关键字直接 `TypeError`，
不会静默丢弃）；`fail_open` 捕获的是 `Exception`，**包括 `TypeError` 这类你自己的代码 bug**
（用错地方会把 bug 变成静默降级）。

### 4.10 `furina_core.sandbox`

**用途**：把模型给出的路径钳在沙箱目录内 —— **路径边界，不是进程沙箱**。

```python
from furina_core.sandbox import PathJail, PathOutOfSandbox

jail = PathJail(settings.sandbox_root)
target = jail.resolve("notes/memo.txt")     # -> 沙箱内绝对路径
jail.resolve("../../etc/passwd")            # -> 抛 PathOutOfSandbox
jail.is_inside(user_path)                   # -> bool，永不抛异常
```

| 符号 | 签名 | 参数要求 / 返回 / 异常 |
|---|---|---|
| `PathJail` | `(root: str \| Path)` | 构造时对 `root` 做一次 `.resolve()`（符号链接必须在这步展开） |
| `.root` | `-> Path` | 解析后的沙箱根（只读） |
| `.resolve` | `(rel_path: str) -> Path` | 空/纯空白 → `ValueError`；绝对路径 → `ValueError`；越界 → `PathOutOfSandbox`。目标**可以不存在**（写新文件） |
| `.is_inside` | `(rel_path: str) -> bool` | 把上面两类拒绝都吃掉，返回 `False`（供审批前预检） |
| `PathOutOfSandbox` | `(root: Path, target: Path)` | `str(e)` 是**给模型看**的一句话（不含真实路径）；真路径在 `.root` / `.target`（给日志） |

**契约与坑**：校验顺序**不能改** —— ①空值 → ②`is_absolute()` 意图检查 → ③拼接 + `.resolve()`
→ ④`is_relative_to()` 结果校验；只有 ④ 不可绕过（Windows 上 `Path("/etc/passwd").is_absolute()`
是 `False`，②挡不住）；判断"在不在里面"**不要用 `str.startswith`**
（`/sandbox-evil` 会被误判为在 `/sandbox` 内）。

### 4.11 `furina_core.limits`

**用途**：进程内令牌桶，限出站调用（桌面端的 LLM 调用防成本失控）。

```python
from furina_core.limits import LocalTokenBucket, RateLimiter, RateLimitExceeded

bucket = LocalTokenBucket(capacity=5, refill_rate=1.0, key="llm")
if await bucket.try_acquire():        # 非阻塞：拿到 True，拿不到 False
    await call_llm()
await bucket.acquire(timeout=30)      # 愿意等：超时抛 RateLimitExceeded
```

| 符号 | 签名 | 参数要求 / 返回 / 异常 |
|---|---|---|
| `LocalTokenBucket` | `(*, capacity: int, refill_rate: float, key="local", initial_tokens: float \| None = None)` | **关键字专用**；`initial_tokens` 默认=满桶；`capacity<=0` 或 `refill_rate<=0` → `ValueError` |
| `.try_acquire` | `async (tokens=1) -> bool` | 非阻塞，**不抛**（`tokens<=0` 或 `tokens>capacity` → `ValueError`） |
| `.acquire` | `async (tokens=1, *, timeout: float \| None = None) -> None` | 超时抛 `RateLimitExceeded(key, retry_after)`；`timeout=None` = 无限等 |
| `await bucket(n)` | `-> bool` | 等价 `try_acquire(n)` |
| `.snapshot()` | `-> {key, tokens, capacity, refill_rate, idle_seconds}` | **只读**，不触发补充，`tokens` 可能偏旧 |
| `.reset()` | `-> None` | 填满（测试/运维用） |
| `RateLimiter` | Protocol：`.key` / `try_acquire` / `acquire` | 结构化类型；web 将来换分布式实现时只需满足它 |
| `RateLimitExceeded` | `(*, key: str, retry_after: float)` | `retry_after` 是**估算**值（按当前令牌数算） |

**契约与坑**：`capacity` 是**突发量**、`refill_rate` 是**稳态速率**（每秒补充令牌数），两件事别混；
`try_acquire` 虽是 `async` 但函数体里**一个 `await` 都没有** —— 这是"无锁也正确"的前提，
内部 `_refill_and_take()` **必须保持同步**；`acquire` 是"小步 sleep + 重试"轮询（5ms–200ms），
最坏多等 ~0.2s；**单进程限流**（多副本部署每进程各一份配额）。

---

## 五、边界：三条红线（机械检查）

| 红线 | 内容 | 检查命令（应无输出） |
|---|---|---|
| 一 | 不 import 任何具体存储后端（`asyncpg`/`psycopg`/`redis`/`lancedb`） | `Select-String -Path "packages\core\src\furina_core\*.py","packages\core\src\furina_core\*\*.py" -Pattern "^\s*(from\|import)\s+(asyncpg\|psycopg\|redis\|lancedb)"` |
| 二 | 依赖单向：`app → core`（core 不 import `furina_web`/`furina_desktop`） | 同上，把组换成 `(furina_web\|furina_desktop)`（**行首必须是 import** 才算；文档里提到 `furina_web` 的散文不算） |
| 三 | 包根零副作用（`__init__.py` 不 import 子模块） | `python -c "import furina_core,sys; print([m for m in ('sqlmodel','fastapi','bcrypt') if m in sys.modules])"` → `[]` |

**允许的框架依赖**（都写在 `pyproject.toml`）：`pydantic`、`sqlmodel` + `sqlalchemy`（共享表定义与会话类型）、
`fastapi`（`Depends` / `get_session`）、`openai`（LLM 客户端工厂，**延迟导入**）、`bcrypt`、`pyjwt`、`python-dotenv`。
"零框架依赖"是早期写下、实测不成立的红线，已废弃为"零存储后端"。

---

## 六、已知限制与坑（用之前先看）

| # | 事项 | 影响 | 建议 |
|---|---|---|---|
| 1 | `settings.sandbox_root` 默认 `Path(".")` | 没设 `SANDBOX_ROOT` 时，**沙箱根 = 进程 CWD** | 启动前显式设环境变量；别依赖默认值 |
| 2 | `.env` 是"向上最多 5 层"的启发式查找 | 打包/发布后可能读到**意料之外位置**的 `.env` | 发布版显式注入环境变量 |
| 3 | `settings` 在模块导入时构造一次 | 运行中改环境变量无效 | 需要热更新就自己重建 `CommonSettings()` |
| 4 | core **不抛 HTTPException** | 忘了映射 `TokenError` → 过期令牌变 **500**（应为 401） | 鉴权入口统一 `except TokenError`（§3.2） |
| 5 | 兼容垫片的密钥来自**进程环境变量** | 与 app 自己的配置是两份来源，容易漂移 | 新代码用 `create_token(jwt_key=...)` |
| 6 | `fail_open` 吞掉所有 `Exception` | 自己的代码 bug 会被当成"下游不可用"静默降级 | 关键路径用 `fail_closed`，或自己收窄 `except` |
| 7 | `CheckpointStore` 运行期**不校验签名** | 同步实现也能通过 `isinstance`，直到真跑图才炸 | 实现后跑一次真实 `astream`；或装 mypy/pyright |
| 8 | `PathJail` 只是路径边界 | 不防"任意代码执行" | 真要隔离得上进程/容器 |
| 9 | `LocalTokenBucket` 是进程内的 | 多副本部署时限流形同虚设 | 分布式配额用网关/Redis 方案 |
| 10 | `errors` 默认文案有**双冒号**（`工具：：a`） | 纯外观问题，模型/用户会看到 | 想清理就改 `default_message` 或模板 |
| 11 | `CircuitBreaker` 的 `HALF_OPEN` 不限并发探测 | 冷却期一过，全部并发请求都会去打下游 | 下游很脆时把 `cooldown_seconds` 调大 |
| 12 | `sandbox.PathJail` / `limits.LocalTokenBucket` **零调用者** | 库里有、产品里没接 | 要么接线（推荐 `PathJail` 替掉 desktop 的复制版），要么删掉 |

---

## 七、自检与版本

```powershell
cd C:\furina-agent
$env:PYTHONPATH = "packages\core\src;apps\web\src;apps\desktop\src"

# ① 本文档的契约（86 项断言，无网络无数据库）
.venv-build\Scripts\python.exe packages\core\tests\smoke_public_api.py

# ② 熔断器 / 令牌桶的并发行为（12 项）
.venv-build\Scripts\python.exe scripts\verify_core.py

# ③ 表模型能不能真的被查询（两种模式**必须分进程**）
.venv-build\Scripts\python.exe scripts\verify_models.py web
.venv-build\Scripts\python.exe scripts\verify_models.py desktop
```

三条红线的机械检查见 §5。文档与代码不一致时：**以脚本为准，并顺手改这份文档**。

**版本**：`furina_core.__version__ == "0.1.0"`（`packages/core/pyproject.toml`）。
改动本库请遵守仓库 `AGENTS.md` 的标记约定（`# ── AI-ASSISTED ──` / `# <- AI 改动` + 复核重点）。

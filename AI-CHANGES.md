# AI 改动清单

> **这份文件是给你（人类）看的复核入口，不是给工具读的。**
> 约定见 [AGENTS.md](AGENTS.md) 二点五
>
> **用法**：按下面顺序复核。每个文件都标了"复核重点"——那些是**我做了判断、而判断权本该在你手里**的地方。
> 复核完一个就把源码里的 `# ── AI-ASSISTED ──` 标记删掉，**标记消失 = 这个文件你已经读懂了**。
>
> 最后更新：本轮"把 `furina_core` 自身修干净 + 写对外 API 说明书"。上一轮的成果对应提交 `c2d232d`；本轮改动**尚未提交**。
> ⚠️ 本轮改动一律带 `# <- AI 改动` 行尾标记 + 文件头 `# ── AI-ASSISTED ──` 复核重点，见 §八 / §九。

---

## 〇、环境与协作（先说这个，否则跑不起来）

### 📋 你以后要用的命令

```powershell
cd C:\furina-agent
$env:UV_CACHE_DIR = "C:\furina-agent\.uv-cache"
$env:UV_PROJECT_ENVIRONMENT = "C:\furina-agent\.venv-build"
uv lock
uv sync --all-packages --frozen
```

| 开关 / 变量 | 不加会怎样 |
|---|---|
| `--all-packages` | **只装根工程的依赖** → 你会只拿到 uvicorn，业务依赖全缺 |
| `--frozen` | uv 每次都要**改写 `uv.lock`**，某些环境只读 → `os error 5` |
| `UV_CACHE_DIR` | uv 缓存写用户目录，被沙箱拒绝 → `Failed to initialize cache` |
| `UV_PROJECT_ENVIRONMENT` | 默认写 `.venv`（旧的那个只剩空壳且删不掉）→ 失败 |

### ⚠️ 已知环境限制（不是代码问题）

| 现象 | 原因 |
|---|---|
| `backend/` 完全只读（新建/删除/移动/改文件全拒） | DSH 沙箱**按具体路径**授权，不递归；`backend/` 从未被授权 |
| `%TEMP%\dsh-*\` 里的目录**存在但写不进去** | 同上 → SQLite 会报 `unable to open database file`。**测试要用仓库内路径** |
| `C:\furina-agent\.git\` 只读 | 所以**我无法 commit / push**，只能你来做 |
| `uv.lock` 只读 | 所以要 `--frozen` |

> 因此：**`backend/` 旧树我一个字都没动，两份副本并存**。
> 等 web / desktop 都能真正启动之后，再由你删旧树（一次 `Remove-Item backend -Recurse -Force`）。

---

## 一、当前状态（可验证的数字）

| 项 | 结果 |
|---|---|
| 全量编译（SyntaxWarning 视为错误） | ✅ 退出码 0 |
| 真实 import | ✅ **71/71**（core 14 / web 29 / desktop 28） |
| core 行为断言 `scripts/verify_core.py` | ✅ 12/12 |
| checkpoint 存储断言 `apps/desktop/tests/smoke_checkpoint.py` | ✅ 14/14 |
| **desktop 入口走完整 lifespan** | ✅ `checkpoint_store = SqliteCheckpointStore` + `graph = CompiledStateGraph` |
| **web 入口启动** | ⚠️ `init_db`(PG) 通过 → `init_redis` 超时（**你机器上 Redis 没起来**）→ 正确回滚 |
| 五条架构红线 | ✅ 全绿 |

---

## 二、三层包结构（本次重构的成果）

```
packages/core/src/furina_core/     14 文件  共享内核
apps/web/src/furina_web/           29 文件  Web 版（部署域名）
apps/desktop/src/furina_desktop/   28 文件  桌面版（开箱即用）
```

**五条架构红线**（可机械检查，脚本见文末）：

1. `core` 零存储后端（不出现 `asyncpg`/`psycopg`/`redis`/`lancedb`）
2. `core` 不依赖 `web`/`desktop`
3. `web` 不依赖 `desktop`
4. `desktop` 不依赖 `web`
5. `desktop/storage/` 不依赖 `agent`/`services`/`api`

---

## 三、⭐ 需要你复核的判断（按"我做了判断"的密度排序）

### 第一梯队：我改了你原本的设计

| # | 文件 | 我改了什么 | 复核重点 |
|---|---|---|---|
| 1 | [packages/core/src/furina_core/__init__.py](packages/core/src/furina_core/__init__.py) | **改了设计红线**：从"零框架依赖"改成"**零存储后端**" | 我最初定的"零框架"**实测不成立**（`models.py` 要 sqlmodel、`storage/session.py` 要 fastapi、`config.py` 要 openai）。我选择**改红线**而不是把文件赶出 core。**如果你不同意，告诉我** —— 那会牵动两个 app 的导入 |
| 2 | [security.py](packages/core/src/furina_core/security.py) | 把 `create_jwt`/`create_access_token`/`create_refresh_token` 合并成 `create_token`，**再加三个兼容垫片** | ① 垫片从**环境变量**读 JWT 密钥（因为 core 拿不到 web 的 settings）② 密钥缺失时**抛错而不给默认值**（fail-closed，别改成默认值） |
| 3 | [agent/build.py](apps/desktop/src/furina_desktop/agent/build.py) | `build_graph` 参数 `saver` → `checkpointer`，并**加解包** | LangGraph 的 `compile()` 有类型检查，只认 `BaseCheckpointSaver`；我的 store 是适配器。**分工**：业务层用协议，装配层交出真 saver |
| 4 | [storage/local_store.py](apps/desktop/src/furina_desktop/storage/local_store.py) | 加公开的 `.saver` 属性 | ⚠️ **这个属性名不能改** —— `build_graph` 用 `getattr(obj,"saver",None)` 找它，改名会静默拿到 `None`，然后报 "Invalid checkpointer provided" |
| 5 | [storage/database.py](apps/web/src/furina_web/storage/database.py) | `create_all` 改成**显式表清单** | 原来是无参的，建的是"所有已注册到 metadata 的表" —— 拆表后**建出哪几张取决于哪些模块恰好被 import**，不报错、只是少建 |

### 第二梯队：新增的入口与行为

| # | 文件 | 说明 | 复核重点 |
|---|---|---|---|
| 6 | [apps/desktop/src/furina_desktop/main.py](apps/desktop/src/furina_desktop/main.py) | **新建**（205 行） | ① **单实例锁**用了平台 API（`msvcrt`/`fcntl`），请实测开两个进程 ② 监听的 host 只允许回环，改成 `0.0.0.0` 会**拒绝启动**（防呆）③ `data/checkpoints.sqlite` 落 CWD，发布版应改 `%APPDATA%` |
| 7 | [apps/web/src/furina_web/main.py](apps/web/src/furina_web/main.py) | **新建**（136 行） | ① 日志初始化从 **import 期**挪到 `run()` 期（**行为变更**）② CORS 默认只允许本机，要放开用 `CORS_ORIGINS` ③ `httpx/openai/urllib3` 压到 WARNING（**防密钥进日志**） |
| 8 | [apps/web/src/furina_web/config.py](apps/web/src/furina_web/config.py) | **新建**（56 行） | `WebSettings` 从 core 搬来（PG/Redis/JWT 是 web 专属），并加 `require_*()` 启动校验 |
| 9 | [agent/nodes/chat.py](apps/desktop/src/furina_desktop/agent/nodes/chat.py) | `State` → `SupervisorState` | 这是**推测性修复**（原代码引的 `State` 根本不存在，文件从来没 import 成功过）。它**仍未接入任何图** |
| 10 | [agent/prompts/loader.py](apps/desktop/src/furina_desktop/agent/prompts/loader.py) | **新建**，消灭硬编码路径 | ⚠️ 打包时 `.txt` **默认不被打进包** —— 这是"本地能跑、打包后崩"的经典陷阱，M0 必须验 |

### 第三梯队：机械改动（读起来快）

| 类别 | 内容 |
|---|---|
| 包名重写 | `app.*` → `furina_core.*` / `furina_web.*` / `furina_desktop.*`，共 100+ 处 |
| 契约拆分 | `schemas/model.py` 24 个类拆成三份：core `enums.py`(1) + web `contracts.py`(15) + desktop `api/agent contracts.py`(9) |
| 表模型拆分 | `models/table.py` 拆成 core `models.py`(User/AgentThreadID) + web `models/table.py`(Conversation/Message) |
| 服务合并 | `services/agent_thread.py` + `repositories/agent_thread_id.py` 合并，数据访问函数加 `db_` 前缀 |
| 依赖声明 | core 补 `fastapi`/`sqlmodel`/`sqlalchemy`/`pydantic`/`openai`；web 补 `asyncpg`/`psycopg`/`redis`/`python-multipart` |

---

## 四、⚠️ 只有"真启动"才暴露的 3 个坑（值得记）

| # | 现象 | 根因 | 教训 |
|---|---|---|---|
| 1 | `Invalid checkpointer provided... Received SqliteCheckpointStore` | LangGraph 的 `compile()` **做类型检查** | 适配器模式遇到"上游要做 isinstance 检查"时，**必须在装配点解包** |
| 2 | 加了 `_unwrap_checkpointer` **仍然报同样的错** | store 把它存成**私有的 `_saver`**，`getattr(obj,"saver",None)` 静默返回 `None` | **`getattr` 带默认值 = 静默失败**。名字对不上不报错，错误在很远的下游炸出来 |
| 3 | smoke 测试断言失败 | ① 我用了 PostgreSQL saver 的表名（**SQLite 是 2 张表，PG 是 3 张**）② `getattr(back.checkpoint, "id", None)` —— 但 `.checkpoint` 是 **dict** | 与 `docs/NOTES.md` 里反复记的"**对象 vs 字典**"是同一个病根 |

---

## 五、验证脚本

```powershell
cd C:\furina-agent
$env:PYTHONPATH = "packages\core\src;apps\web\src;apps\desktop\src"

# core 行为断言（12 项）
.venv-build\Scripts\python.exe scripts\verify_core.py

# checkpoint 存储断言（14 项）
.venv-build\Scripts\python.exe apps\desktop\tests\smoke_checkpoint.py
```

**架构红线的机械检查**（应全部无输出）：

```powershell
# 1. core 零存储后端
Select-String -Path "packages\core\src\furina_core\*.py","packages\core\src\furina_core\**\*.py" `
  -Pattern "^\s*(from|import)\s+(asyncpg|psycopg|redis|lancedb)"
# 2. 其它四条
Select-String -Path "apps\desktop\src\**\*.py" -Pattern "^\s*(from|import)\s+furina_web"
```

---

## 六、我没做、也没擅自动的

| 没做 | 为什么 |
|---|---|
| 修 `execute_node` 空函数体 / `goto="execute_node"` 指向未注册节点 / `decision_review` 拼写 | 那是 M3 的活。本轮只调结构 —— 结构清楚了修起来才有地方下手 |
| 拆 `agent/dependencies.py`（234 行） | 它是**唯一没被搬运破坏的文件**，动它风险不对等 |
| 写 `nodes/supervisor.py` 的 5 个业务节点 | M1/M2 的实现工作（现在全是 `NotImplementedError`） |
| 删 `backend/` 旧树 | **权限不足**（见第〇节）。等你确认新树能跑之后自己删 |
| 删 `backend/_t_review.py` / `_exp_a6.py` / `_demo_prompt.py` | 开发脚手架，未跟踪。**别用 `git add -A`** |

---

## 七、待你决定的（我列出来但没替你选）

1. **`nodes/chat.py` 保留还是删？** 它是死文件；我保留是因为它的逻辑就是 M1 要用的节点
2. **`security.py` 的三个兼容垫片，什么时候删？** 干净做法是 web 侧显式传 `jwt_key`，然后删垫片
3. **desktop 的数据目录**：现在还落 `data/`（CWD），发布版应该是 `%APPDATA%\furina-agent\` —— 要引 `platformdirs` 吗？
4. **`docs/PLAN.md` 里被推翻的章节**（Rust 网关 / Rust RAG / Docker / 多用户认证）要不要清理？我说过"留着作废的理由比没理由更危险"

---

## 八、本轮修复：三处"契约对不上"（+ 一处更深的地基问题）

> 起因：把 `furina_core` 的公开 API 逐个对着调用点验了一遍。
> 结论：上一轮的「真实 import 71/71 ✅」**一处都没覆盖到** —— 这三个缺陷全都在 import 之下，
> 只有"真发一次请求 / 真查一次库"才会暴露。

### 8.1 修了什么

| # | 改前的实测现象 | 根因 | 修法 | 文件（都带 AI 标记） |
|---|---|---|---|---|
| ①② | **每个带鉴权的请求都 500**：`AttributeError: 'TokenPayload' object has no attribute 'get'`；过期令牌则因为 `except HTTPException` 接不住 `TokenError` 而 500（应为 401） | core 的兼容垫片 `decode_token_compat` **签名兼容、返回类型不兼容**（老实现返回 dict，新的返回 dataclass） | 20 处 `.get("x")` → 属性访问（`token_type`/`jti`/`session_id`/`subject`/`expires_at`）；`except HTTPException` → `except TokenError`，翻成 401 | [auth/dependencies.py](apps/web/src/furina_web/auth/dependencies.py)、[services/user.py](apps/web/src/furina_web/services/user.py)、[routers/auth.py](apps/web/src/furina_web/routers/auth.py) |
| ①b | **每次刷新令牌都 401**：`user_refresh` 依赖令牌里的 `name`，而 core 的 `create_token` **刻意不写** `name` | 载荷契约变了，调用点没跟 | 新增 `session` 参数（路由同步加 `Depends`），按 `sub` 查库取用户名；顺带把非法 uuid 从 500 改成 401 | 同上 |
| ② | Redis 一起来就崩：`TypeError: CircuitBreaker.__init__() takes 1 positional argument but 2 were given`（排在 `await redis.ping()` **之后**，所以一直被"Redis 没起来"掩盖） | core 熔断器构造改成**全关键字**且不再持有 redis 客户端，调用点还在传位置参数 | `RedisFuse(redis)` → `RedisFuse(name="redis")` | [storage/redis_client.py](apps/web/src/furina_web/storage/redis_client.py) |
| ③ | **任何真实 ORM 查询**（web 与 desktop **都**）在 `configure_mappers` 阶段抛 `InvalidRequestError ... relationship("list['Conversation']")` | 见 8.2 —— 两个独立成因叠加 | ① 删掉 core 的 `User.conversations`（core 不该认识 web 的表）；② `Conversation.user` 改单向；③ 去掉 web 表模型的 `from __future__ import annotations` | [packages/core/src/furina_core/models.py](packages/core/src/furina_core/models.py)、[apps/web/src/furina_web/models/table.py](apps/web/src/furina_web/models/table.py) |

### 8.1.1 顺带改的两处（与上述缺陷无关，先说清楚免得你在 diff 里被绊一下）

| 改动 | 说明 |
|---|---|
| 两处 docstring 拼写：`urina_web.models.tables` → `furina_web.models.table`（[core/models.py](packages/core/src/furina_core/models.py)、[web/models/table.py](apps/web/src/furina_web/models/table.py)） | 原文首字母 `f` 丢了（疑似编辑器/BOM 事故），纯注释修正，不影响行为 |
| 恢复文件的**字节约定**（4 个文件补回 UTF-8 BOM、2 个文件改回 LF） | 我第一遍改完发现 diff 里混进了 BOM 丢失 / CRLF 两种无关改动，已按 HEAD 的原始字节逐文件复原并复核（`git diff --numstat` 里现在没有这类噪音） |

### 8.2 ⭐ ③ 是两件事，不是一件（最值得记的一条）
| 成因 | 机制 | 修法为什么是那样 |
|---|---|---|
| **跨模块引用** | `User.conversations: list['Conversation']` 写在 core，而 `Conversation` 在 web。注解要在**定义它的模块**里解析 → 解析不到 → SQLModel 把整串 `list['Conversation']` 当关系目标交给 SQLAlchemy | 共享内核不能引用"只有一边有"的类；反过来，desktop 的注册表里根本没有 `Conversation`，**任何**指向它的关系都必然配置失败 |
| **前向引用 + future import** | web 表模型加了 `from __future__ import annotations`（老的单文件表**没有**）。注解全变字符串，`Conversation.messages: list['Message']` 引用的 `Message` 在文件下面才定义 → pydantic 求值失败 → 同样把整串注解丢给 SQLAlchemy | 去掉 future import 后，`list['Message']` 立刻求值成"list + 字符串 'Message'"，SQLModel 只交出字符串，**由 SQLAlchemy 注册表在 configure_mappers 时按名字解析** —— 谁先谁后都行。**该文件不要再加回这行** |

**教训**：`import` 全过 ≠ 能跑。上一轮的验证方式是"导入 + 12 项行为断言"，而这两个坑都发生在
"第一次真正查询"时。所以本轮补了两个脚本（§8.3），并且把"一定要真发一次请求/真查一次库"写进结论。

### 8.3 本轮新增的验证脚本（都可以直接跑）

```powershell
cd C:\furina-agent
$env:PYTHONPATH = "packages\core\src;apps\web\src;apps\desktop\src"

# ORM 冒烟（两种模式**必须分进程**跑，理由写在脚本里）
.venv-build\Scripts\python.exe scripts\verify_models.py web       # -> RESULT: PASS
.venv-build\Scripts\python.exe scripts\verify_models.py desktop   # -> RESULT: PASS

# 鉴权/刷新/登出 的载荷冒烟（不打 PG、不打 Redis，全部打桩）
.venv-build\Scripts\python.exe apps\web\tests\smoke_auth_payload.py   # -> 15/15 PASS
```

本轮跑过的全部验证（都是实测，不是推断）：

| 检查 | 结果 |
|---|---|
| 6 个改动文件编译（SyntaxWarning 视为错误） | ✅ OK |
| 三个包全量 import（core 15 + web 30 + desktop 29） | ✅ 74/74 |
| `scripts/verify_core.py` | ✅ 12/12（未回归） |
| `scripts/verify_models.py web` / `desktop` | ✅ PASS / PASS（改前两个都 FAIL） |
| `apps/web/tests/smoke_auth_payload.py` | ✅ 15/15（改前：合法令牌也是 500） |
| `apps/desktop/tests/smoke_checkpoint.py` | ✅ 14/14（未回归） |

### 8.4 本轮**没做**的（留给你的判断）

| 项 | 为什么没动 |
|---|---|
| ④ `core.sandbox.PathJail` / `core.limits.LocalTokenBucket` **零调用者** | desktop 的 [agent/tools/path_jail.py](apps/desktop/src/furina_desktop/agent/tools/path_jail.py) 自己复制了一份边界检查（没有空值检查、没有 `is_inside`）。接线会改动工具层异常类型（`.path` vs `.target`），**这是你的设计选择，不是 bug 修复** |
| `errors.py` 两个异常类的 `else` 分支不调 `super().__init__()` | 是**原有行为**，改了会变 `args`；且 `agent/dependencies.py` 的调用方式还没验证过类型 |
| `fail_open` 捕获所有 `Exception`（连 TypeError 这类代码 bug 一起吞） | 是上一轮的**有意取舍**，要收窄得先知道下游会抛什么 |
| `CheckpointStore` 的 `runtime_checkable` 只查属性名（不查签名） | 协议表达不了；要真约束得装 mypy/pyright |
| **提交 / push** | `.git` 目录只读，我做不到 —— 按 §〇 的老规矩，只能你来 |

---

## 九、本轮（第二段）：把 `furina_core` 自身修干净 + 对外 API 说明书

> §八 修的是"**调用点**与库对不上"；这一轮修的是"**库自己**的契约缺陷"，
> 并把"当黑盒用"所需的信息一次写进 `packages/core/README.md`。

### 9.1 修了什么（都在 `packages/core/src/furina_core/`）

| # | 缺陷（改前实测） | 根因 | 修法 | 文件 |
|---|---|---|---|---|
| ① | `MissingRequiredArgumentError` / `InvalidArgumentError` 的 **else 分支**：`e.args == ()`、`str(e) == ""`、`e.message` 退化成 `list` | 原作者漏调 `super().__init__()`（if 分支调了，else 没有） | else 分支补上同样的调用，`message` 统一为 `str` | [errors.py](packages/core/src/furina_core/errors.py) |
| ② | 四个子类的 `message` 参数**被静默忽略**（签名里有、函数体从不读它） | 搬运时没发现；文档却说"用 `message` 把错误消息传给基类" | 传了就 `super().__init__(message)` 并跳过默认文案；不传时行为不变 | 同上 |
| ③ | 缺 `JWT_SECRET_KEY` 时兼容垫片抛 `TokenError("invalid")` | 语义错位：**配置错误伪装成"令牌无效"**，调用方会翻成 401，排障时极难定位 | 改抛 `RuntimeError`（与 `CommonSettings.require_api_key()` 同类：配置问题 → 500） | [security.py](packages/core/src/furina_core/security.py) |
| ④ | 两处**文档漂移**：<br>· `checkpoint.py` 写"6 个方法 1:1 定义""补上第 7、8 个成员" —— 实际协议只有 **7 个成员**（上游 6 个 async 方法里省略了 `aget`，它是 `aget_tuple` 的包装）<br>· `storage/__init__.py` 写"不 import sqlmodel" —— 可 `models.py` 明明 import 了 | §八 改红线时只改了 `__init__.py`，别处的旧说法没跟着改 | 按实测更正（上游行号也重新核对过：416/428/442/467/490/510） | [checkpoint.py](packages/core/src/furina_core/checkpoint.py)、[storage/__init__.py](packages/core/src/furina_core/storage/__init__.py) |

### 9.2 新增文件（AI 生成，带复核重点）

| 文件 | 作用 |
|---|---|
| [packages/core/README.md](packages/core/README.md) | **对外 API 说明书**（黑盒视角）。结构按你的要求重排过：**§1 用途总览 → §2 导入规则 → §3 契约与硬规则（含"异常→状态码映射表""参数传递规则表"）→ §4 逐模块 API（用途·签名·参数要求·契约）**，之后才是 §5 红线、§6 已知限制、§7 自检这些杂项 |
| [packages/core/tests/smoke_public_api.py](packages/core/tests/smoke_public_api.py) | **README 的可执行版本**：86 项断言（含红线一/二的静态检查），覆盖 core 全部公开符号；无网络、无数据库、无 Redis |

> 为什么非要配一个脚本：本仓库栽过"文档说已验证、树里跑不起来"的坑（AGENTS.md 一点五）。
> 规矩定死：**改了 README 就同步改这个脚本**，两者冲突时以脚本为准。

### 9.3 本轮实测（全部亲跑）

| 检查 | 结果 |
|---|---|
| `packages/core/tests/smoke_public_api.py` | ✅ **86/86 PASS**（含 ①②③ 的新断言 + 红线静态检查；改①②③前分别是 FAIL） |
| `scripts/verify_core.py` | ✅ 12/12 |
| `scripts/verify_models.py web` / `desktop` | ✅ PASS / PASS |
| `apps/web/tests/smoke_auth_payload.py` | ✅ 15/15（③ 改成 RuntimeError 后未回归） |
| `apps/desktop/tests/smoke_checkpoint.py` | ✅ 14/14 |
| 三个包全量 import | ✅ 74/74 |
| 改动文件编译（SyntaxWarning 视为错误） | ✅ OK |

### 9.4 本轮**没做**的（仍然是你的决定）

| 项 | 为什么没动 |
|---|---|
| 删掉 `security.py` 的三个兼容垫片（迁移到 web 显式传 key） | 它们是**公开 API**，删掉要同时新增一个 web 侧 token 适配模块；属设计决定而非 bug。垫片注释里写了完整迁移路径，README §4.5 也标了"新代码请用 `create_token`" |
| `core.sandbox.PathJail` / `core.limits` 的接线或删除 | desktop 工具层自己复制了一份路径检查；接线会改工具层的异常类型契约 |
| `errors` 默认文案的双冒号（`工具：：a`） | 会动用户/模型可见字符串，已在 README §5 记为已知瑕疵 |
| 提交 / push | `.git` 只读 |

---

## 十、2026-10-22：审批链路修复（阶段 2 / 第一刀）

> 依据：`docs/2026-10-22-审批系统V1-阶段1-只读审查.md`、`docs/2026-10-22-审批系统V1-总体设计与实施方案.md`
> 范围：**只改 desktop**。`backend/` 未动，`apps/web/` 未动。
> 本刀只做"让图能跑到审批门并正确恢复"，**审批表 / 幂等 / 统一执行器还没做**（阶段 2 第二刀 + 阶段 3）。

### 10.1 改动文件

| 文件 | 改了什么 | 复核重点 |
|---|---|---|
| `apps/desktop/src/furina_desktop/agent/state.py` | ① `CoderState` 补 `subagent_task`；② `coder_messages` 给默认值；③ 两个审批字段改成纯 `dict` | ③ 是刻意的：Pydantic 对象落 checkpoint 会触发 LangGraph 的"未注册类型"告警（实测已出现），改 dict 后三种 saver 行为一致。形状校验移到 `execute_node` |
| `apps/desktop/src/furina_desktop/agent/dependencies.py` | ① 重写 `classify_tool_calls`：按 name 分三堆，返回 `(risky, safe, unknown)`；② 重写 `handle_review_fn`：按 `tool_call_id` 对齐、拦未知 id、去掉三处裸 `raise` | ① 返回顺序变了，调用方已同步；`registry` 参数已删除（原本没用到）。② 拒绝仍是"整批不执行"（现状语义），是否改逐条执行待确认 |
| `apps/desktop/src/furina_desktop/agent/nodes/coder.py` | ① `load_prompt` → `aload_prompt`；② 注册 `prevalidate_node` / `execute_node`；③ `should_continue` 改为去 prevalidate；④ 修 `decision_review` 拼写；⑤ `execute_node` 补实现 | ② `execute_node` 目前只做校验 + 分发，**高风险工具仍由 ToolNode 直接执行** —— 这是阶段 2 的临时边界，阶段 3 必须换执行器。⑤ 载荷非法时 fail-closed |
| `apps/desktop/src/furina_desktop/services/agent_thread.py` | 补 `select/func/update` 导入 | 只补导入，SQL 语义未动 |
| `apps/desktop/tests/smoke_approval_flow.py` | **新增**：真实图 + 真实工具 + 真实 interrupt/resume；只 stub LLM | 不是"模拟审批"：审批门、ToolNode、文件写入都是真的 |

### 10.2 实测结果（全部亲跑）

| 检查 | 结果 |
|---|---|
| `apps/desktop/tests/smoke_approval_flow.py` | ✅ **15/15**（安全工具直通、批准写入、拒绝不写、未知工具拦截、路径越界拦截） |
| `apps/desktop/tests/smoke_checkpoint.py` | ✅ 14/14 |
| `packages/core/tests/smoke_public_api.py` | ✅ 86/86 |
| `scripts/verify_core.py` | ✅ 12/12 |
| `scripts/verify_models.py desktop` / `web` | ✅ PASS / PASS |

### 10.3 本轮暴露的新 bug（阶段 1 被 B1 挡住，够不到）

`model_node` 里 `await load_prompt("coder")` —— `load_prompt` 是同步函数，返回 `str`。
实测 `TypeError: object str can't be used in 'await' expression`。
已改成 `aload_prompt`。

### 10.4 仍未做（下一刀）

| 项 | 状态 |
|---|---|
| 审批表 + 状态枚举 + repository | ❌ 未做 |
| 桌面业务数据库会话（`app.state.async_session`） | ❌ 未做（`/agent/threads` 仍不可用） |
| 审批 API（列表 / 决策 / resume） | ❌ 未做（`/agent/resume` 仍是 `pass`） |
| 统一执行器 + DB 审批状态校验 + 幂等键 | ❌ 未做（阶段 3） |
| SSE 桥接（`agent_stream` 仍是 `NotImplementedError`） | ❌ 未做 |

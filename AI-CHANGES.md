# AI 改动清单

> **这份文件是给你（人类）看的复核入口，不是给工具读的。**
> 约定见 [AGENTS.md](AGENTS.md) 二点五
>
> **用法**：按下面顺序复核。每个文件都标了"复核重点"——那些是**我做了判断、而判断权本该在你手里**的地方。
> 复核完一个就把源码里的 `# ── AI-ASSISTED ──` 标记删掉，**标记消失 = 这个文件你已经读懂了**。

---

## 〇、环境状态（先说这个，否则跑不起来）

### ✅ 已修复

| 问题 | 原因 | 解决 |
|---|---|---|
| `pwsh` 全部命令失败 | `C:\furina-agent` 缺 `WRITE_OWNER` | 补上（备份+回滚命令在 `.dsh-acl-recovery\`） |
| `backend/`、`.venv/` 只读 | DSH 沙箱**按具体路径**授权，不递归；这些目录从未被授权 | 用新目录（`.venv-build`）绕开 |
| `uv sync` 卸了 67 个包没装回来 | **★ 我造成的**：根 `pyproject.toml` 改成工作区根后，根只剩 `uvicorn` 一个依赖，默认 `uv sync` 就只装它 | 加 `--all-packages` |
| `uv` 所有子命令报 `os error 5` | 它每次都想改写 `uv.lock`，而该文件只读 | 加 `--frozen` |
| `uv_build` 报 "Expected a Python module at ..." | 缺 `src/<包名>/__init__.py` | 已补齐三个成员的 `__init__.py` |

### 📋 你以后要用这三条命令

```powershell
cd C:\furina-agent
$env:UV_CACHE_DIR = "C:\furina-agent\.uv-cache"          # uv 缓存别写用户目录（沙箱拒绝）
$env:UV_PROJECT_ENVIRONMENT = "C:\furina-agent\.venv-build"  # 别用那个只读的 .venv
uv sync --all-packages --frozen
```

**三个开关缺一不可**：

- `--all-packages`：不加则只装根工程依赖（**就是 67 个包消失的原因**）
- `--frozen`：不加则 uv 要改 `uv.lock` 而失败
- `UV_PROJECT_ENVIRONMENT`：不加则写 `.venv`（只读）而失败

**如果你的终端能写 `.venv`**（比如重启 DSH 会话或直接用自己的终端），可以简化成：

```powershell
Remove-Item .venv -Recurse -Force
uv venv --python 3.12
uv sync --all-packages
```

---

## 一、AI 新建的文件（需要你复核）

> **优先读这 3 个** —— 它们是**全新写法**，你的既有知识里没有对应物，
> 而且我把"为什么这么写"完整写进了 docstring（各含 3~4 节原理讲解）：
>
> | 文件 | 行数 | 该文件的 docstring 教什么 |
> |---|---|---|
> | [limits/local_bucket.py](packages/core/src/furina_core/limits/local_bucket.py) | 193 | ①令牌桶原理（capacity≠速率）②**"无锁为何成立"**：asyncio 单线程 + 无 await 的同步段就是临界区 ③为什么用惰性补充而非后台定时器 |
> | [circuit_breaker.py](packages/core/src/furina_core/circuit_breaker.py) | 215 | ①三态熔断解决什么 ②⭐**"为什么令牌桶不用锁、熔断器必须用锁"**——同一套并发环境下两个相反决定，判据是"临界区里有没有 await" ③为什么熔断器不吞异常 |
> | [sandbox.py](packages/core/src/furina_core/sandbox.py) | 123 | ⭐**两道门为什么缺一不可**：`is_absolute()` 挡不住"根相对路径"（含具体漏网输入），真正的门是 `is_relative_to()`；为什么不能用 `startswith` |
>
> 其余 6 个是**搬运 + 注释**，读起来快，按下面的表逐项核对即可。

### 1. `packages/core/` —— 共享内核（本次主要交付物）

零存储、零框架、零 LLM SDK。依赖只有 `pyjwt` / `bcrypt` / `python-dotenv`。

| 文件 | 行数 | 性质 | 复核重点 |
|---|---|---|---|
| [limits/local_bucket.py](packages/core/src/furina_core/limits/local_bucket.py) | 193 | **重写+注释** | 硬约束：`_refill_and_take` 里**不能有 await**。已过 6 项实测 |
| [circuit_breaker.py](packages/core/src/furina_core/circuit_breaker.py) | 215 | **重写+注释** | 三个 `_locked` 方法**只在持锁时调用**（命名约定，非类型强制）。已过 6 项实测 |
| [sandbox.py](packages/core/src/furina_core/sandbox.py) | 123 | **重写+注释** | 空值判断 `and`→`or`；`.resolve()` 两处都不能省。已过 7 项实测 |
| [circuit_policies.py](packages/core/src/furina_core/circuit_policies.py) | ~88 | 搬运 | `fail_open` 现在捕获**所有** Exception → **代码 bug 也会被静默降级**，这是最值得推翻的一处 |
| [config.py](packages/core/src/furina_core/config.py) | ~82 | 搬运 | `require_*()` 取代 import 期 raise 是**行为变更**；`_find_dotenv()` 是启发式 |
| [security.py](packages/core/src/furina_core/security.py) | ~120 | 搬运 | ①`TokenError` 取代 `HTTPException`，**调用方必须跟着改** ②`session_id` 改可选，确认 web 顶号校验没漏 |
| [limits/base.py](packages/core/src/furina_core/limits/base.py) | ~58 | 新建 | `RateLimiter` 是 Protocol，**项目没装类型检查器 → 这层约束目前是纯文档** |
| [limits/\_\_init\_\_.py](packages/core/src/furina_core/limits/__init__.py) | ~20 | 新建 | 包内唯一有 import 副作用的 `__init__` |
| [\_\_init\_\_.py](packages/core/src/furina_core/__init__.py) | ~20 | 新建 | 包根"零 import"是有意设计 |

### 2. 工作区骨架

| 文件 | 说明 |
|---|---|
| [pyproject.toml](pyproject.toml) | **我整体重写过**。原为单工程（29 行含全部业务依赖）；现为工作区根。**业务依赖全部下移到各成员** |
| [packages/core/pyproject.toml](packages/core/pyproject.toml) | 依赖从 10 个收紧到 3 个 |
| [apps/web/pyproject.toml](apps/web/pyproject.toml) | **刻意不含** langgraph/langchain/psycopg |
| [apps/desktop/pyproject.toml](apps/desktop/pyproject.toml) | **刻意不含** email-validator。`lancedb` 待补（你的桌面存储） |
| [apps/web/src/furina_web/\_\_init\_\_.py](apps/web/src/furina_web/__init__.py) | 骨架 + 迁移待办（包名、MessageRole、create_all） |
| [apps/desktop/src/furina_desktop/\_\_init\_\_.py](apps/desktop/src/furina_desktop/__init__.py) | 骨架 + 四个已知坑（PG saver、硬编码路径、字段拼写、空节点） |

### 3. 验证脚手架与文档

| 文件 | 说明 |
|---|---|
| [scripts/verify_core.py](scripts/verify_core.py) | **可运行的自测**，12 项断言。跑法：`.venv-build\Scripts\python.exe scripts\verify_core.py`。验完可删 |
| [AGENTS.md](AGENTS.md) | 我新建。含"分析要周全 / 意见要精辟 / 别全信 PLAN / AI 标记约定" |
| [AI-CHANGES.md](AI-CHANGES.md) | 本文件 |
| [.gitignore](.gitignore) | 追加 6 组规则：前端构建产物（**`frontend/src-tauri/target` 有 4.25 GB，原来没被忽略**）、探针、个人数据、`.uv-cache/` |

---

## 二、AI 修改过的**既有**文件（只有 3 个，各 1~3 行）

| 文件 | 改动 | 状态 |
|---|---|---|
| [backend/app/agent/registry.py](backend/app/agent/registry.py) | 第 30-32 行共 3 行 | `ReadFileTool.name` → `read_file_tool.name`（**Pydantic v2 禁止类级访问字段**）；`tool.args.key()` → `for arg in tool.args`。**已验证**：`{file_path, query, text}` |
| [backend/app/agent/agent_dependencies.py](backend/app/agent/agent_dependencies.py) | 第 7 行 1 行 | 删掉不存在的 `ToolMessagefrom`。**已验证**：import 通过 |
| [backend/app/core/redis_client.py](backend/app/core/redis_client.py) | 第 20 行 1 行 | `await aioredis.from_url(...)` → 去掉 `await`（redis 8 里它是**同步**工厂）。**已验证**：`iscoroutinefunction` 为 False |

> 这三处已包含在提交 **`bb8a3e3`** 里。逐行查看：
> ```powershell
> git show bb8a3e3 -- backend/app/agent/registry.py backend/app/agent/agent_dependencies.py backend/app/core/redis_client.py
> ```
> 共同点：**都是"名字/对象用错"，不是逻辑错**，所以只能靠 import 验证，不能靠推理。

---

## 三、AI **没有**改的东西（明确划界）

| 没碰 | 为什么 |
|---|---|
| `backend/` 下其余**所有**文件 | 沙箱只允许我写"本会话创建或首次写入"的文件。这符合"新树生长、旧树不动"的路线 |
| `handle_review_fn` 的三个裸 `raise` + 死代码 | 不是 import 问题；且**无调用者**，改了也验证不了 |
| `classify_tool_calls` 的 `set(dict)` / `difference` 没并 safe | 另一个函数的逻辑错，属于审批链路那一仗 |
| `coder.py` 的 `except: pass` / `decision_review` 拼写 / 硬编码 prompt 路径 | 属于 desktop 迁移那一仗 |
| `docs/PLAN.md` | **没动**。但它的存储与架构结论已被你的 SQLite+LanceDB 决定推翻 —— 是否同步更新**等你点头** |
| `frontend/` | 没动。4.25 GB 构建产物已被 `.gitignore` 挡住 |

---

## 四、验证状态

### ✅ 已实测通过（12 项，2026 本次会话）

```
=== LocalTokenBucket ===
  [PASS] capacity=2, take 3 times               got=[True, True, False]
  [PASS] acquire waits ~1.0s for refill
  [PASS] over-capacity request raises ValueError
  [PASS] timeout raises RateLimitExceeded (retry_after=0.80s)
  [PASS] reset() refilled the bucket
  [PASS] 20 concurrent tasks, capacity=5        got=5          <- 无锁正确性

=== CircuitBreaker ===
  [PASS] after 2 failures (threshold=2)         got='OPEN'
  [PASS] OPEN short-circuits without calling downstream
  [PASS] first probe after cooldown             got='fine'
  [PASS] state after 1 probe                    got='HALF_OPEN'
  [PASS] state after 2 probes (probe_success=2) got='CLOSE'
  [PASS] 10 concurrent failures -> tripped      got='OPEN'     <- 修掉的竞态
```

另：`compileall` 退出码 0；core 零违规依赖（grep 0 命中）；`uv workspace list` 认 4 个成员；三个成员 import 全部成功。

### ✅ `sandbox.py` 的 7 项实测（证明"第一道门挡不全"这个论断）

```
PureWindowsPath('/etc/passwd').is_absolute() = False     <- 第一道门确实放行
而 (root / '/etc/passwd') = C:\etc\passwd                 <- root 真的被替换掉了

[ALLOWED] normal relative path          -> C:\furina-agent\sandbox\notes\memo.txt
[BLOCKED] empty string                  -> ValueError
[BLOCKED] whitespace only  <- 原版会漏过  -> ValueError
[BLOCKED] None             <- 原版会崩    -> ValueError
[BLOCKED] dotdot escape                 -> PathOutOfSandbox
[BLOCKED] root-relative   <- 第一道门的漏网之鱼 -> PathOutOfSandbox   ★ 第二道门接住了
[BLOCKED] drive-absolute                -> ValueError
is_inside: 'a.txt'=True, '../x'=False, ''=False, '   '=False
```

### ❌ 未验证

- 熔断器**真实下游**行为未验（只验了状态机，用的假函数）
- `security.py` / `config.py` / `sandbox.py` **未运行**（没有真实 PG / Redis / 令牌）
- 整个 `backend/` 仍跑不起来（`.venv` 空 + `agent_dependencies.py` 依赖关系未在旧环境验过）

---

## 五、待你决定的三件事

1. **`docs/PLAN.md` 要不要同步更新？** 它的存储方案（PG+Redis）与 Rust 网关理由都已被推翻。按 AGENTS.md 的准则，**过时文档比没文档更危险**
2. **desktop 的配置项有哪些？** `sqlite_path` / `lance_dir` / 沙箱根目录 —— 定了才能写 `DesktopSettings`
3. **`lancedb` 何时加回 desktop 的 `pyproject.toml`？** 现在缺着（你确认它是桌面存储后才该加）

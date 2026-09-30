# 开发环境与常用命令

> 建立：本次重构会话 ｜ 针对 **uv workspace** 结构（`packages/core` + `apps/web` + `apps/desktop`）
> 目的：让"新 clone 一台机器怎么跑起来"和"日常改代码用什么命令"有唯一答案。

---

## 一、前置

| 依赖 | 版本要求 | 说明 |
|---|---|---|
| Python | **≥3.12** | `pyproject.toml` 里写死了 `requires-python = ">=3.12"` |
| uv | **≥0.12.5** | 本仓库用 uv workspace 管三个包，不用 pip / poetry |
| PostgreSQL | 16+ | **只有 web 版需要** |
| Redis | 7+ | **只有 web 版需要** |
| 无 | —— | **桌面版零外部服务**（SQLite + LanceDB 都是嵌入式的） |

> 桌面版的设计目标就是"双击即用"：不需要用户装数据库。这是选 SQLite/LanceDB 的理由。

---

## 二、⭐ 三条命令（本轮踩坑的最终结论）

```powershell
cd C:\furina-agent
$env:UV_CACHE_DIR = "C:\furina-agent\.uv-cache"
$env:UV_PROJECT_ENVIRONMENT = "C:\furina-agent\.venv-build"
uv sync --all-packages --frozen
```

### 每个开关为什么必须有

| 开关 | 不加会怎样 | 根因 |
|---|---|---|
| `--all-packages` | **只装根工程的依赖** → 你只会得到 4 个包（uvicorn 及其依赖），业务依赖全缺 | 根 `pyproject.toml` 改成了**工作区根**，自身只声明 `uvicorn`。三个成员（core/web/desktop）的依赖默认**不装** |
| `--frozen` | `error: failed to write to file uv.lock: 拒绝访问 (os error 5)` | 某些环境下 `uv.lock` 只读；不加这个开关 uv 每次都要**改写 lock 文件** |
| `UV_PROJECT_ENVIRONMENT` | 想写 `.venv` 但写不进去 | 默认环境目录是 `.venv`。若它只读/被占用，必须指向新目录 |

### 如果你能正常写 `.venv`（大多数情况）

那就不需要那两个环境变量，用最朴素的方式：

```powershell
cd C:\furina-agent
Remove-Item .venv -Recurse -Force
uv venv --python 3.12
uv sync --all-packages
```

---

## 三、日常命令

```powershell
# 装/更新依赖（改过任何 pyproject.toml 之后）
uv sync --all-packages

# 只装某一个成员（排查"这个包到底谁依赖"时很好用）
uv tree --package furina-desktop        # 看 desktop 的依赖树
uv tree --package furina-web            # 看 web 的依赖树

# 加依赖 —— 注意 --package 指定加给谁
uv add --package furina-core pyjwt
uv add --package furina-web  fastapi
uv add --package furina-desktop langgraph

# 跑脚本
uv run python scripts/verify_core.py

# 跑某一端的服务（等迁移完成后）
uv run --package furina-web     python -m furina_web
uv run --package furina-desktop python -m furina_desktop
```

### ⚠️ 一条纪律：加依赖必须指定 `--package`

```
uv add redis              # ❌ 加到根工程 → 根不该有业务依赖
uv add --package furina-web redis    # ✅ 加给真正用它的那个包
```

**为什么重要**：`--all-packages` 装的是三个成员的**并集**。如果依赖乱加在根上，
"依赖分离"就退化成"一个大依赖集合"，而分离正是这次重构的核心目标。

---

## 四、验证命令（改完代码先跑这个）

```powershell
# core 的 12 项行为断言（令牌桶 + 熔断器）
uv run python scripts/verify_core.py

# 期望输出：12 个 [PASS]
```

**为什么要用脚本而不是"看着跑通了"**：这批代码（令牌桶、熔断器）的正确性
不体现在"能运行"，而体现在**边界行为**——并发计数、超时、状态迁移。
这些只有断言能验。见 [AI-CHANGES.md](../AI-CHANGES.md) 的验证记录。

---

## 五、目录与包的对应关系

```
furina-agent/                        ← 工作区根（不是应用，只做成员声明）
├─ pyproject.toml                    [project] name = furina-agent-workspace
│                                    [tool.uv.workspace] members = ["packages/*", "apps/*"]
├─ uv.lock                           ★ 全工作区共享一个锁文件（这是 uv workspace 的核心价值）
├─ packages/core/                    → 包名 furina-core → import furina_core
│   └─ src/furina_core/
├─ apps/web/                         → 包名 furina-web → import furina_web
│   └─ src/furina_web/
└─ apps/desktop/                     → 包名 furina-desktop → import furina_desktop
    └─ src/furina_desktop/
```

**三条硬规则**：

1. **包名和 import 名不一样**：`furina-core`（带横线，PyPI 规范）对应 `furina_core`（带下划线，Python 标识符）。这不是笔误。
2. **必须用 `src/` 布局**：`apps/web/src/furina_web/` 而不是 `apps/web/furina_web/`。因为 `src/` 布局能保证"只有真正安装进环境的包才 import 得到"——**这正是验证依赖分离是否成立的前提**。
3. **`app` 这个包名已废弃**：原来所有代码都是 `from app.xxx import ...`，三个成员都叫 `app` 会撞车（且**不报错**，取决于 `sys.path` 顺序）。已改名为三个独立包名。

---

## 六、验证依赖分离是否真的成立

这是判断"重构有没有白做"的**客观标准**：

```powershell
# web 端不应该能 import 到 langgraph
uv run --package furina-web python -c "import langgraph"
# 期望：ModuleNotFoundError  ← 说明 web 真的没背上 agent 的依赖

# desktop 端不应该能 import 到表单校验库
uv run --package furina-desktop python -c "import email_validator"
# 期望：ModuleNotFoundError
```

> ⚠️ 注意：由于 `--all-packages` 会把三个成员的依赖装进**同一个环境**，
> 上面两条在"全装"的情况下**会失败**（因为三个包都在同一个 `.venv` 里）。
> 要严格验证，得单独给某个成员建环境：
>
> ```powershell
> $env:UV_PROJECT_ENVIRONMENT = ".venv-web-only"
> uv sync --package furina-web
> uv run --package furina-web python -c "import langgraph"   # 这时才应该是 ModuleNotFoundError
> ```

---

## 七、排障

| 症状 | 原因 | 解决 |
|---|---|---|
| 只装了 4 个包 | 漏了 `--all-packages` | 加回去 |
| `failed to write uv.lock: 拒绝访问` | lock 文件只读（权限或沙箱） | 加 `--frozen`；或让自己对 `uv.lock` 有写权限 |
| `Failed to initialize cache at ...` | uv 缓存目录写不进去 | 设 `UV_CACHE_DIR` 到可写位置 |
| `Expected a Python module at: src/xxx/__init__.py` | 缺 `__init__.py` | `uv_build` 要求 `src/<包名>/__init__.py` 存在 |
| 改了 `pyproject.toml` 但没生效 | uv 用了旧的 lock | 去掉 `--frozen` 让它重新解析，或 `uv lock` |
| 想彻底重来 | 环境是消耗品 | `Remove-Item .venv* -Recurse -Force` 后重跑第二节 |

---

## 八、待补（还没做）

- [ ] `README.md` 的"快速开始"（现在还是 0 字节）
- [ ] web 的 `docker-compose.yml`（PG + Redis + FastAPI）
- [ ] web / desktop 各自的 `Dockerfile`
- [ ] 测试框架选型（pytest）与 `tests/` 目录
- [ ] CI（GitHub Actions）
- [ ] `.env.example`（现在只有 `.env`，别人 clone 下来不知道该填什么）

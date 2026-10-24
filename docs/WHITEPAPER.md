# 芙宁娜 Agent 开发白皮书

> 版本：2026-10-23 ｜ 定位：**稳定的"是什么 / 为什么这么设计"文档**
> 配套：进度看 [PROGRESS.md](PROGRESS.md)，任务看 [TODO.md](TODO.md)，协作纪律看 [../AGENTS.md](../AGENTS.md)
>
> 写作纪律：**事实与推断分开标注**；每条设计写清楚"代价"；不把规划当已实现。

---

## 0. 一句话

**一个装在 Windows 上、双击即用的 AI 桌面助手：芙宁娜角色扮演 + 代码 Agent（写操作需人工审批）。**

技术上是：**LangGraph 手搓 StateGraph（主管图 + coder 子图）+ SQLite checkpoint + 工具风险分级 + interrupt/resume 审批**。

---

## 1. 产品定义与边界

### 1.1 目标优先级

| 优先级 | 目标 | 判据 |
|---|---|---|
| 1 | **自用** | 自己每天愿意打开它 |
| 2 | **求职作品** | 能讲清架构取舍、有可演示的东西 |
| 3 | **开源** | 别人 clone 后能装上并跑起来 |

### 1.2 明确不做（本阶段）

| 不做 | 理由 |
|---|---|
| 本地模型兜底 | 首次进入必须配置大模型密钥；打包模型会让安装包变成 GB 级 |
| 服务端托管密钥 | BYOK，服务端不碰 token、不计费 |
| 非 OpenAI 兼容格式 | 只认 `base_url` + `api_key` + `/v1/chat/completions` |
| 多用户 / 注册登录 | 单机应用，没有顶号、黑名单语义 |
| Docker / 要求用户装服务 | "双击即用"的定义 |
| RAG 独立进程 | 桌面端检索频率≈0，LanceDB 进程内足够 |
| Web 版（本阶段） | Web 是副产品；`furina-core` 为它保留共用能力 |
| Rust 网关 / Rust RAG / 三平台包 | 先只做 Windows；性能问题用压测数字决定，不先造网关 |

### 1.3 三个可执行验收锚点

| 锚点 | 判据 |
|---|---|
| **A 骨架贯通** | 无 Python 的 Windows 机器上：安装 → 填密钥 → 校验通过 → 说一句话得到回复 |
| **B 芙宁娜可对话** | 连续 3 轮，她能引用 1 条来自 `knowledge/` 的世界观知识 |
| **C 审批闭环** | Agent 提出写文件 → 展示 diff → 批准后文件真出现；拒绝后真没有且模型收到打回 |

---

## 2. 系统形态

### 2.1 双端独立后端（2026-10-23 定案）

```
packages/core/   furina_core  —— 共享内核（零存储、零框架、零 LLM SDK）
apps/web/        furina_web   —— Web 版：PostgreSQL 16 + Redis
apps/desktop/    furina_desktop —— 桌面版：SQLite + LanceDB，零外部服务
knowledge/       芙宁娜语料（32 文件 / 约 125 KB）
scripts/         验证脚本；experiments/ 为归档实验
```

关键点：

- **双端各自独立后端**，只共享 `packages/core`。旧单体 `backend/`（双端共用）已于 2026-10-23 删除。
- 桌面版**只监听 `127.0.0.1`**，拒绝绑定 `0.0.0.0`（`apps/desktop/src/furina_desktop/main.py:299-307`）。
- 桌面版有**单实例文件锁**，防止两个进程各有一个令牌桶导致限流翻倍。

### 2.2 分层

```
HTTP / SSE
   │
   ▼
api/（路由） → services/（业务） → storage/（SQLite / saver）
   │
   └─► agent/（编排层）
         ├─ build.py        主管图装配（唯一 compile(checkpointer=...) 的地方）
         ├─ state.py        SupervisorState / CoderState
         ├─ nodes/coder.py  coder 子图（手搓 ReAct）
         ├─ tools/          工具与注册表
         ├─ dependencies.py 审批载荷、裁决、回填
         └─ stream.py       LangGraph → SSE 桥（当前未实现）
```

---

## 3. 核心架构

### 3.1 主管图 + coder 子图

目标形态（`build.py:10-21` 的注释）：

```
START ─▶ [用户画像注入] ─▶ [意图路由] ─┬─(闲聊)───▶ [LLM 生成(流式)] ──┐
                                      ├─(需检索)─▶ [RAG 检索] ────────┤
                                      └─(需工具)─▶ [子代理调度] ──────┤
                                                                      ▼
                                                      [持久化] ─▶ END
```

**现状**：`build_graph` 只接了 `START → coder_graph → END`（`build.py:103-109`），五个主管业务节点仍是 `raise NotImplementedError`。

coder 子图（`nodes/coder.py:210-259`）：

```
START → prepare → model ─┬─(有 tool_calls)─▶ prevalidate ─┬─(全安全)─▶ tools ─┐
                         │                                ├─(有高风险)─▶ review(interrupt) → execute ─┘
                         │                                └─(未知工具)─▶ 回填错误 → model
                         └─(无 tool_calls)─▶ END
```

### 3.2 状态模型（`state.py`）

**SupervisorState**（主图）：

| 字段 | 类型 | 说明 |
|---|---|---|
| `messages` | `Annotated[list, add_messages]` | 唯一对话真相 |
| `mode` | `Literal["roleplay","code"]` | 双模式开关（当前**必填无默认**） |
| `user_name` | `str \| None` | 用户画像 |
| `personal_preference` | `str \| None` | 用户偏好 |
| `rag_result` | `str \| None` | 检索结果 |
| `subagent_task` | `str \| None` | 派给子代理的任务简报 |

**CoderState**（子图）：

| 字段 | 类型 | 说明 |
|---|---|---|
| `subagent_task` | `str \| None` | 与主管**逐字同名**才共享 |
| `coder_messages` | `Annotated[list, add_messages]` | **私有**，故意不叫 `messages` |
| `pending_reviews` | `dict \| None` | 审批载荷快照（JSON 可序列化） |
| `decision_reviews` | `dict \| None` | 人类裁决 |

**三条硬约束**：

1. **状态里只放 JSON 可序列化的数据**。审批载荷存 `dict`，到节点边界再 `model_validate`；直接存 Pydantic 对象会触发 LangGraph checkpoint 的未注册类型告警。
2. **父子消息字段名必须不同**（`messages` vs `coder_messages`），否则可能共享同一 channel。名字不同是零成本保险。
3. **子图不配 checkpointer**：只有最外层主管图编译时传 saver；子图自带 saver 会让中断被它自己接住，主管永远看不见（静默失败）。

### 3.3 工具分级与审批

工具注册表（`tools/registry.py:28-31`）：

```python
CODER_TOOLS = [read_file_tool, write_file_tool, bocha_search_tool]
SAFE_TOOLS  = {read_file_tool.name, bocha_search_tool.name}  # 只读、无副作用
RISKY_TOOLS = {write_file_tool.name}                         # 需审批
```

分类规则（`dependencies.py:168-189`）：

- **SAFE** → 直接进 `tools_node`
- **RISKY** → 构造 `ReviewRequest` → `review_node` 调 `interrupt()` 暂停
- **UNKNOWN** → **fail-closed**，整批回填 `ToolMessage` 让模型改

> ⚠️ 当前 `tool_node = ToolNode(coder_tools, ...)` 仍包含高风险工具（`coder.py:62`）。审批通过后经 `goto="tools_node"` 执行。V2 阶段 C 要做"统一执行器 + DB 审批校验"。

### 3.4 HITL 两层反馈契约

**口诀：主管能等到的走第一层；等不到、需要人或外层的走第二层。**

| 场景 | 走哪层 | 谁处理 |
|---|---|---|
| 子代理干完，汇报结果 | 第一层：工具返回 / `AgentResult` | 主管做质量判断 |
| 子代理想改文件 | 第二层：`approval_required` | 最外层 UI + 人 |
| 子代理崩溃/超时 | 第二层：`error` 终态 | 最外层兜底 |

审批链路（当前实现）：

```
prevalidate_node  → 构造 ReviewRequest（含 path/diff/old_hash）
review_node       → interrupt(payload)        ← 图暂停，checkpoint 落盘
  (人批准/拒绝)
Command(resume=ReviewDecision)
execute_node      → model_validate → handle_review_fn
handle_review_fn  → 全批准 goto tools_node；有拒绝则回填 ToolMessage → model_node
```

### 3.5 持久化与 checkpoint

- **主管图**：`build_graph(store)` 里 `compile(checkpointer=...)`，这是唯一编译 checkpointer 的地方（`build.py:108`）。
- **桌面**：`SqliteCheckpointStore`（`storage/local_store.py`），lifespan 顺序为"业务库 → checkpoint → 图"（`main.py:187-216`）。
- **Web**：PostgreSQL saver + 业务库 PG + Redis。
- **删除线程**：先 `adelete_thread` 清快照，再删业务壳表；反序会留下不可自愈的孤儿。
- **resume 是节点级重跑**，不是精确续执行：`interrupt()` 之前的代码会重放，写在它之前的落库必须幂等。

### 3.6 沙箱与路径安全

- 只接受**相对路径**，拒绝绝对路径（`dependencies.py:16-34`）。
- `(root / rel).resolve()` 后必须 `is_relative_to(root)`。
- ⚠️ Windows 上 `PureWindowsPath('/etc/passwd').is_absolute()` 为 `False`，且 `(root/'/etc/passwd')` 会变成 `C:\etc\passwd`——所以**只靠 `is_absolute()` 不够**，必须做 resolve 后比较。
- 已知欠账：`build_write_review` 的 diff 头仍写绝对路径（`dependencies.py:131`）；目录会被误判为新文件（`:122-129`）。

### 3.7 流式观测（待实现）

- `stream_mode=["messages","values"]`，chunk 是 `(mode, payload)` 二元组。
- **中断挂在 `values` 流的 payload 上**（字段名 `interrupts`），不在 `messages` 流。
- 事件契约目标：`token | tool_start | tool_end | approval_required | error | done`。
- "run 结束"事件必须标明：**正常结束** 还是 **带 pending 中断结束**，否则前端无法区分"没审批"和"审批没冒泡"。

---

## 4. 关键决策（ADR）

| # | 决策 | 理由 | 代价 / 状态 |
|---|---|---|---|
| 1 | **弃用 `create_agent`，手搓 StateGraph** | 图结构固定、middleware 拿不到结构化 diff、黑盒难排查 | 要自己维护路由与循环；已定案 |
| 2 | **只有最外层图编译 checkpointer** | 官方迁移指南；子图自带 saver 会截获中断 | 子图必须靠父图冒泡；需实测确认 |
| 3 | **父子消息字段名不同** | 防共享 channel；字段名差一个字母会静默不共享 | 命名要人工保持一致；已落地 |
| 4 | **子代理每次白纸** | 隔离靠"新调用"天然获得；配独立 saver = 状态泄漏 | 主管必须把上下文摊平成任务简报 |
| 5 | **状态只放 JSON 可序列化数据** | 跨 InMemory/SQLite/PG 行为一致，不随 LangGraph 版本坏 | 节点边界要做 Pydantic 校验 |
| 6 | **工具风险硬编码名单 + 未知 fail-closed** | 简单、可审计；不让模型自报风险 | 加工具必须记得登记 |
| 7 | **双端独立后端** | 桌面零外部服务；Web 多用户需求不同 | 共享代码必须下沉到 core，否则两份漂移 |
| 8 | **uv workspace 按"共享内核 vs 产品"切** | 按 web/desktop 复制会出两份会漂移的安全实现 | 包名/import 名不同，需纪律 |
| 9 | **桌面删掉 services/repositories 两层** | 单进程只有一个消费者，分层是负债 | 数据访问函数用 `db_` 前缀保留可读性 |
| 10 | **桌面用 SQLite 而非 PG** | 用户不能装数据库 | SQLite saver 质量需实测；FK 默认关闭 |
| 11 | **审批载荷存 `dict` 不存 Pydantic 对象** | 避免 checkpoint 未注册类型告警 | 形状校验责任转移到执行节点 |

---

## 5. 契约定义

### 5.1 审批契约（`agent/contracts.py`）

```python
class WritePreview(BaseModel):
    tool_call_id: str
    path: str                 # 沙箱相对路径
    is_new_file: bool
    old_hash: str | None      # 乐观锁：审批时的文件内容哈希
    added: int
    removed: int
    diff: str

class ReviewRequest(BaseModel):
    type: Literal["review_request"] = "review_request"
    action: Literal["review_request"] = "review_request"
    requests: list[WritePreview]

class ItemDecision(BaseModel):
    tool_call_id: str
    action: ReviewAction      # approve / reject
    reason: str | None

class ReviewDecision(BaseModel):
    type: Literal["review_decision"] = "review_decision"
    decisions: list[ItemDecision]
```

### 5.2 规划中的结果契约（**未落码**）

`9.8-agent架构契约.md` 定义的 `AgentResult` / `AgentError` 目前**全仓库不存在**：

```python
class AgentResult(BaseModel):
    status: Literal["success", "error"]
    summary: str
    error: AgentError | None
    artifacts: list[str] | None

class AgentError(BaseModel):
    kind: Literal["task_failed", "tool_failed", "timeout", "invalid_request"]
    detail: str
```

### 5.3 V2 数据模型（已落库）

`Thread → Task → Execution → Approval` 四层：

| 实体 | 要点 |
|---|---|
| `AgentThreadID` | 会话壳，业务归属与鉴权 |
| `AgentTask` | 业务任务；`redelegation_key` 唯一，防重复重委派 |
| `AgentExecution` | 一次执行；`graph_thread_id` 是 LangGraph 运行键 |
| `ApprovalRequest` | 一行=一次工具调用；`idempotency_key` 唯一 |

状态机要点（2026-10-24 与 `task/enums.py` 对齐；此前本节写的 `expired/cancelled` 并不存在）：

- 任务态 `TaskStatus`：`QUEUED / RUNNING / WAITING_APPROVAL / SUSPENDED / COMPLETED / FAILED / CANCELLED`
- 执行流程态 `ExecutionStatus`：`CREATED / RUNNING / WAITING_APPROVAL / SUSPENDED / VALIDATION_FAILED / COMPLETED / FAILED / CANCELLED`
- 审批态 `ApprovalStatus`：`PENDING / APPROVED / REJECTED / REVOKED`（**没有 `EXPIRED`**）
- 工具执行态 `ToolExecutionStatus`：`NOT_STARTED / RUNNING / SUCCEEDED / FAILED / UNKNOWN`
- **`APPROVED` ≠ 已执行**；只有 `APPROVED + NOT_STARTED` 能被条件 UPDATE 认领。
- **超时只置 Task/Execution 为 `SUSPENDED`，不改审批状态**；取消待审用 `REVOKED`。
- 写后读回不一致或超时 → `UNKNOWN`，**禁止自动重试**。
- 合法迁移表落码在 `task/lifecycle.py`（T19）：终态不可出、不允许回退到 `QUEUED`。
- T19 变更（2026-10-24）：`RUNNING → SUSPENDED` 是**受保护边**，默认 API 拒绝；
  只有 `suspend_after_resume_failure` 在确认该 Execution 下没有任何工具开始执行后才可以迁。
  `SUSPENDED` 因此有两种来源：审批超时（T21）与图恢复失败（T23）。

---

## 6. 工程纪律（摘自 AGENTS.md）

1. **先实测，再断言**。静态推断必须标注为推断。
2. **区分"它崩了"和"它错了"**。崩了能被运行抓到；错了是静默的（布尔写反、字段名拼错、集合语义写反），更危险。
3. **给结论必须带证据**：文件 + 行号 + 实测输出。
4. **主动找反面证据**：问"什么情况下这个判断是错的"。
5. **修值 vs 修结构**：让报错消失 vs 让错误不可能发生，要明确指出属于哪种。
6. **只做有调用者的修改**：没接线、没载荷流过的代码先重构 = 给没打地基的房子挑窗帘。
7. **AI 改动打标记**：`# ── AI-ASSISTED ──` 或 `# <- AI 改动`，并写"复核重点"。
8. **提交完立刻 push**（防 git 事故）。

---

## 7. 已知陷阱（静默失败清单）

> 这些坑的共同点：**不报错**。只能靠用例和读码发现。

| 陷阱 | 后果 |
|---|---|
| 子图自带 checkpointer | 中断不冒泡，图正常跑完 |
| 父子都声明 `messages` | 共享 channel；字段名差一字母 → 静默不共享 |
| `add_messages` 追加语义 | 第二次调 coder 残留上一轮消息 |
| `interrupt_on` 工具名拼错 | fail-open，静默放行 |
| 非法 JSON tool_call | `tool_calls=[]`，图正常结束但工具没跑 |
| `decision_review` vs `decision_reviews` | Pydantic 静默丢弃 |
| `getattr(obj,"saver")` 对 `_saver` | 返回 None，下游才报 "Invalid checkpointer" |
| `bind_tools` 返回值丢弃 | 模型从未见工具 |
| `autocommit` 未设 | checkpoint 从不 commit，恢复不了且不报错 |
| 默认值撞真实语义（`added=0`、`old_hash="str"`） | 假载荷通过校验 |
| 目录被当成文件 | `build_write_review` 误判为新文件 |
| resume 重放 `interrupt()` 之前的代码 | 重复计费 / 重复副作用 |

---

## 8. 技术栈与开发环境

### 8.1 技术栈

| 层 | 选型 |
|---|---|
| 工作区 | uv workspace |
| 共享内核 | `furina-core`（零存储 / 零框架 / 零 LLM SDK） |
| Web | FastAPI + PostgreSQL 16 + Redis |
| 桌面 | FastAPI + SQLite + LanceDB（待接） |
| 编排 | LangGraph（手搓 StateGraph） |
| LLM | DeepSeek（OpenAI 兼容，`ChatOpenAI`） |
| 前端 | Web HTML；桌面 Tauri + React（脚手架） |

### 8.2 命令

```powershell
cd C:\furina-agent
$env:UV_CACHE_DIR = "C:\furina-agent\.uv-cache"
$env:UV_PROJECT_ENVIRONMENT = "C:\furina-agent\.venv-build"
uv sync --all-packages --frozen

uv run python scripts/verify_core.py                 # 期望 12 项 PASS
uv run --package furina-desktop python -m furina_desktop
```

### 8.3 本机约束

- Python ≥ 3.12，uv ≥ 0.12.5；`src/` 布局；包名 `furina-*` ↔ import `furina_*`。
- 加依赖必须 `--package`，否则依赖分离退化成一个集合。
- WSL2 + Radeon 8060S（gfx1151）走 DXG：必须 `HSA_ENABLE_DXG_DETECTION=1`；Ollama 只能 CPU。
- 数据放 WSL 内部文件系统（`~/`），不放 `/mnt/c/`。
- 桌面版零外部服务；Web 版才需要 PG/Redis。

---

## 9. 术语表

| 术语 | 含义 |
|---|---|
| 主管图 | 最外层 StateGraph，持有 checkpointer 与长期记忆 |
| coder 子图 | 编程助手子代理，手搓 ReAct 循环 |
| 白纸 | 子代理每次调用不携带上次状态 |
| HITL | Human-in-the-loop，人工审批 |
| RISKY/SAFE | 工具风险分级；UNKNOWN 一律 fail-closed |
| anchor A/B/C | 三个可执行验收锚点 |

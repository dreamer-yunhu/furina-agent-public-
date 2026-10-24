# 芙宁娜 Agent 开发进度记录

> 起始：2026-08-29 ｜ 最后更新：2026-10-23
> 定位：**只记已发生的事实**。设计看 [WHITEPAPER.md](WHITEPAPER.md)，任务看 [TODO.md](TODO.md)。
>
> 记录规则：
> - 每条尽量带证据（文件/行号/命令/测试结果）；没有证据的标 **【推断】**。
> - "文档说已完成"不算证据，只有代码或实测算。
> - 没跑过的测试要明确写"未复跑"。

---

## 0. 当前状态总览（2026-10-23）

| 能力 | 状态 | 证据 |
|---|---|---|
| coder 子图 ReAct 循环 | ✅ | `apps/desktop/.../nodes/coder.py:210-259` |
| 工具分级（SAFE/RISKY/UNKNOWN） | ✅ | `tools/registry.py:28-31`、`dependencies.py:168-189` |
| HITL 审批（图内链路） | ✅ | `smoke_approval_flow.py` 15/15（2026-10-22 记录，10-23 未复跑） |
| 桌面 SQLite checkpoint | ✅ | `storage/local_store.py`、`main.py:196-216` |
| 桌面业务库 + 本地用户 seed | ✅ | `storage/database.py:46-95` |
| V2 阶段 A 持久化（三表） | ✅ | `packages/core/src/furina_core/task/models.py:52/91/125`；21/21 |
| HTTP 流式桥 `POST /agent` | ✅ | `agent/stream.py`；`smoke_stream_bridge.py` 37/37、`smoke_http_resume.py` 16/16 |
| 审批恢复入口 `POST /agent/resume` | ✅ | `api/agent.py` 三条 409 判据；HTTP 冒烟 16/16 |
| 主管图业务节点（画像/路由/RAG/生成/持久化） | ❌ | `agent/build.py:33-91` 全 `NotImplementedError` |
| 任务表运行时接线 | ❌ | `furina_core.task` 仅测试引用 |
| 前端 | ❌ | 脚手架 |
| 打包 / Tauri 进程管理 / 密钥校验 | ❌ | 未开始（M0） |

**一句话**：**"用户 → 子代理 → 流式 → 审批 → 恢复"这段已经能跑通（HTTP 冒烟为证）；缺的是主管图本身（画像/路由/RAG/生成/持久化），以及任务表接线。**

> 2026-10-24 补充：流式桥的关键事实是**必须 `subgraphs=True`**。不开的话，run 停在 interrupt 时 `messages` 流一个 token 都不吐，resume 时才把中断前的消息整条重放（见 `stream.py` 模块 docstring 的实测记录）。

---

## 1. 时间线

### 2026-08-29 · 立项
- 产出 `PLAN.md`（已在文档合并时清理，可从 git 历史查看）：定位、目标架构、Rust 网关/RAG 设想。
- 注：本文后来多处被推翻，**以代码为准**。

### 2026-09-05 · 本地 GPU 推理打通
- WSL2 + Radeon 8060S（gfx1151）跑 llama.cpp HIP 版。
- chat 服务 `127.0.0.1:11435`（deepseek-coder 6.7b，约 38–47 tok/s）；embed `11436`（bge-m3 Q8）。
- 关键约束：`HSA_ENABLE_DXG_DETECTION=1`、`LD_LIBRARY_PATH` 含 `~/.rocm-dxg`；Ollama 只能 CPU。

### 2026-09-06 · 存储与线程壳
- 确立双存储：业务壳表 `AgentThreadID`（归属/鉴权）+ checkpointer 快照（运行态）。
- `build_graph(saver)` 工厂化；checkpointer 放 lifespan + `app.state`，不进路由。
- 实测：同 thread_id 第二次调用能恢复上下文。
- 坑：`autocommit` 未设 → checkpoint 从不 commit，恢复不了且不报错。

### 2026-09-07 · 事件契约与删除顺序
- 删除顺序定案：先 `adelete_thread` 清快照，再删壳表；反序留孤儿。
- 多智能体路线初选 A（子代理=工具），后来改为 B（子图节点）。

### 2026-09-08 · 架构契约与 HITL 调研
- 产出 `9.8-agent架构契约.md`：主管/子代理同形态、组合+依赖注入、主管唯一记忆、子代理白纸、子代理间不直连、两层反馈契约。
- HITL 调研 6 个项目源码：AutoGen 无 `HumanInputBehavior`、CrewAI 核心无 `HumanInputTool`。
- 当时结论：用 `HumanInTheLoopMiddleware`（只适用 `create_agent`）。

### 2026-09-10 · 强类型 State 重构
- `messages` 单字段 → `SupervisorState` / `CoderState` 强类型 Pydantic 模型。
- 实测：`langchain` 1.3.18 / `langchain-core` 1.6.1 均无 `file_management` 模块。

### 2026-09-11 · 中断冒泡验证
- 真 LLM 端到端实测：结果字典含 `__interrupt__`，`SNAPSHOT next=('coder_graph',)`。
- 修正旧认知：子代理不应派生独立 thread_id（那是已停维护的 `langgraph-supervisor` 的旧做法）。

### 2026-09-14 · 主管/coder State 设计
- 产出 `9.14-主管与coder状态设计.md`：字段设计、消息隔离、A-1~A-7 实验清单。
- **A-1~A-7 全部未跑**（A-6 是整套设计的地基）。这是当时的头号未验证项。
- 已预测但未验证的坑：`coder_messages` 跨轮残留。

### 2026-09-15 · 路由定案
- 走 **B 路线（子图作为节点）**，`subagent_result` 字段不再需要。
- 审批粒度拍板：`ItemDecision` + `ReviewDecision`，支持逐个审批。

### 2026-09-16 · uv workspace 重构
- 拆成 `packages/core` + `apps/web` + `apps/desktop`；切分线是"共享内核 vs 产品"。
- 实测：71/71 import、core 断言 12/12、checkpoint 14/14、desktop lifespan 起图。
- Web 端：PG 通过；Redis 未起时超时并正确回滚。
- 坑：`PureWindowsPath('/etc/passwd').is_absolute()` 为 False；路径安全必须 resolve 后 `is_relative_to`。

### 2026-09-30 · 审批链路修复（V1 阶段 1/2）
- 修复 B1–B9：`subagent_task` 字段、`classify_tool_calls` 重写、`prevalidate_node`/`execute_node` 注册、`decision_reviews` 拼写、`handle_review_fn` 三处裸 `raise`、桌面 DB session、缺 import。
- `handle_review_fn` 接通；提示词改走 `prompts/loader.py`。
- 实测：`smoke_approval_flow.py` 15/15（真图、真工具、真 interrupt，仅 stub LLM）。

### 2026-10-22 · 审批 V1/V2 设计与 V2 阶段 A
- 产出 V1 总体设计、V1 阶段 1 只读审查、V2 任务层级迁移方案。
- V2 阶段 A 落库：`AgentTask` / `AgentExecution` / `ApprovalRequest` 三表；条件 UPDATE 仓库；SQLite 外键开启；本地用户 seed。
- 实测：`smoke_task_models.py` 21/21；`smoke_checkpoint.py` 14/14；core 86/86；`verify_models.py` desktop/web 均 PASS。
- 遗留：任务表运行时零接线；高风险工具仍在 ToolNode；统一执行器未做。

### 2026-10-24 · 流式桥 + 审批恢复打通（T1/T2/T3/T15/T16）
- 先做形状探测（`scripts/experiments/probe_stream_v3.py`）再动手，得到三条硬事实：
  ① 不开 `subgraphs`，停在 interrupt 的 run 不吐 token；② 中断在 `payload["__interrupt__"]`，子图/根图各报一次且 id 相同；③ 归属在 namespace 前缀里。
- `agent_stream`：`subgraphs=True` + `["messages","updates","values"]`，事件封闭集 `token/tool_start/tool_end/approval_required/error/done`。
- `POST /agent/resume`：线程归属(404) → 是否挂起(409) → 决定逐条对齐(409) → `Command(resume=)` 流式续跑。
- 挂起期间新消息：按最保守策略返回 `error/thread_suspended`，不启动新 run（Q2 仍未拍板）。
- 顺带修 T15（diff 头不再含绝对路径）与 T16（目标是目录时明确拒绝）。
- T14：全批准后、执行前重读目标文件比 `old_hash`；文件被改/被建/被删一律整批作废并回填模型，不覆盖。
- 实测：`smoke_stream_bridge.py` 37/37；`smoke_http_resume.py` 16/16；`smoke_old_hash.py` 8/8；既有四套 15/15、14/14、21/21、86/86 全绿。

### 2026-10-24（续）· 依赖升级 + T13 + 真模型端到端
- `uv lock --upgrade` 全量升级：langgraph 1.2.11→1.2.17、langchain 1.3.18→1.4.7、langchain-core 1.6.1→1.7.0、openai 2.45→3.37、pydantic 2.13.4→2.14.1、sqlalchemy 2.0.54→2.1.6。回滚备份 `uv.lock.bak-2026-10-24`。
- 升级暴露缺口：SQLAlchemy 2.1 的异步扩展不再隐式带 `greenlet` → `sqlalchemy.ext.asyncio` ImportError。改为声明 `sqlalchemy[asyncio]>=2.0.51`。
- 帧形状回归：升级后用 `probe_stream_v3.py` 重验，`subgraphs=True` 下的三元组、`__interrupt__`、namespace 归属全部不变。
- 真模型端到端（DeepSeek）：`POST /agent` → `tool_start` → `approval_required` → `done=interrupted`；`POST /agent/resume` → `tool_end` → 逐 token 流式 → `done=completed`，文件内容正确。**升级前写入的挂起 checkpoint 在升级后成功恢复**。
- T13：`prepare_node` 进入子图先 `RemoveMessage(REMOVE_ALL_MESSAGES)` 再追加本轮任务；resume 不经过该节点，不影响中断恢复。`smoke_coder_isolation.py` 7/7。
- 实测暴露的三个问题已修：
  ① lifespan 启动时 `ensure_sandbox_root()`（缺就建，失败拒绝启动）；
  ② `WriteFileTool` 在 `_resolve` 之后自动建父目录（仅沙箱内）；
  ③ IO 异常统一走 `_safe_error_message`，只回相对路径，绝对路径只进日志。
  实测：`smoke_tool_safety.py` 20/20；用不存在的 `SANDBOX_ROOT` 起服务，目录被自动创建且 `/healthz` 正常。
- T34：`WritePreview` 增加 `creates_dirs`（缺失的祖先目录，由浅到深），`build_write_review` 计算；字段穿过 interrupt/SSE 到达前端。`smoke_tool_safety.py` 25/25、`smoke_stream_bridge.py` 38/38。

### 2026-10-24（续二）· T18 审批服务（幂等创建）
- 先做 T18-0 只读审计（`docs/audit/2026-10-24-T18-0-审计结论与待拍板.md`），用 5 个探针确认：
  commit 失败后 session 进入 `PendingRollbackError`、SAVEPOINT 可行、并发同 key 只落一行、
  `task_id`/`execution_id` 可错配、SQLite 时间读出为 naive 且比较抛 TypeError。
- 拍板后实施 `packages/core/src/furina_core/task/service.py`：
  `canonical_args_json` / `compute_args_hash` / `derive_idempotency_key`（不含 args_hash）/
  `as_utc` / `ApprovalConflict` / `create_or_get_approval`（SAVEPOINT + flush）。
- 未改 schema、依赖与 repository 提交接口；T19/T20/MCP 均未触碰。
- 实测：`smoke_approval_service.py` 33/33；`smoke_task_models.py` 21/21；core 86/86；import OK。

### 2026-10-24（续三）· T19 生命周期服务
- T19-0 审计（`docs/audit/2026-10-24-T19-0-审计报告.md` + 决策上下文）：实测任意跳转、
  跨 repository 调用部分提交、无状态一致性约束；拍板 Q1–Q8 全部按建议。
- T19-1 `task/lifecycle.py`：Task 7 态 / Execution 8 态迁移表 + `is_legal_*` 纯函数；
  终态无出口、禁止回退 `QUEUED`。矩阵穷举 49 + 64 对。
- T19-2 `task/lifecycle_service.py`：`transition_task` / `transition_execution` /
  `transition_pair`（同一事务，任一侧失败整体回滚）/ `create_execution_for_task`；
  统一返回 `TransitionOutcome`（APPLIED/ILLEGAL/CONFLICT/NOT_FOUND/SCOPE_MISMATCH）。
  repository 的两个 `transition_*` 加 `commit: bool = True` 并在内部做静态合法性校验。
- Q8：修正 `WHITEPAPER §5.3` 与实际枚举不一致的审批态描述。
- 实测：`smoke_lifecycle.py` 55/55；`smoke_task_models.py` 21/21；`smoke_approval_service.py` 33/33；全量 11 套全绿。
- 未验证：跨进程并发、PostgreSQL 行为。

### 2026-10-23 · 删除旧单体 + 文档合并
- 删除 `backend/`（60 个跟踪文件）；未跟踪语料 32 文件迁至 `knowledge/`；实验脚本归档 `scripts/experiments/`。
- 实测：`import furina_desktop.main` → **IMPORT OK**。
- 文档合并为三份：本文件 + `WHITEPAPER.md` + `TODO.md`；旧文档移入 `docs/archive/`。

---

## 2. 已验证清单（可复现）

| 检查 | 结果 | 时间 |
|---|---|---|
| `import furina_desktop.main` | ✅ IMPORT OK | 2026-10-23 |
| `apps/desktop/tests/smoke_stream_bridge.py` | ✅ 38/38 | 2026-10-24 |
| `apps/desktop/tests/smoke_old_hash.py` | ✅ 8/8 | 2026-10-24 |
| `apps/desktop/tests/smoke_coder_isolation.py` | ✅ 7/7 | 2026-10-24 |
| `apps/desktop/tests/smoke_approval_service.py` | ✅ 33/33 | 2026-10-24 |
| `apps/desktop/tests/smoke_lifecycle.py` | ✅ 55/55 | 2026-10-24 |
| `apps/desktop/tests/smoke_tool_safety.py` | ✅ 25/25 | 2026-10-24 |
| 真模型端到端（DeepSeek，含跨版本恢复） | ✅ | 2026-10-24 |
| `apps/desktop/tests/smoke_http_resume.py` | ✅ 16/16 | 2026-10-24 |
| `apps/desktop/tests/smoke_approval_flow.py` | ✅ 15/15 | 2026-10-24 复跑 |
| `apps/desktop/tests/smoke_task_models.py` | ✅ 21/21 | 2026-10-22 |
| `apps/desktop/tests/smoke_checkpoint.py` | ✅ 14/14 | 2026-10-22 |
| `packages/core/tests/smoke_public_api.py` | ✅ 86/86 | 2026-10-22 |
| `scripts/verify_core.py` | ✅ 12/12 | 2026-09-16 |
| `scripts/verify_models.py desktop/web` | ✅ PASS / PASS | 2026-10-22 |
| PG checkpointer 跨调用恢复 | ✅ | 2026-09-06 |
| 子代理 interrupt 冒泡（真 LLM） | ✅ | 2026-09-11 |
| V2 三表 + 外键 + 唯一约束 | ✅ | 2026-10-22 |

### 复跑命令

```powershell
cd C:\furina-agent
.\.venv-build\Scripts\python.exe apps\desktop\tests\smoke_approval_flow.py
.\.venv-build\Scripts\python.exe apps\desktop\tests\smoke_checkpoint.py
.\.venv-build\Scripts\python.exe apps\desktop\tests\smoke_task_models.py
.\.venv-build\Scripts\python.exe packages\core\tests\smoke_public_api.py
```

---

## 3. 未验证清单（假设 / 推断）

| # | 未验证项 | 破坏力 | 备注 |
|---|---|---|---|
| A | Python 后端打包成可执行文件，在无 Python 机器上跑 | ⭐⭐⭐ | 不成立则退回"本地 Web 应用" |
| B | Tauri 可靠拉起/探活/回收 Python 子进程 | ⭐⭐ | 僵尸进程、端口冲突 |
| C | 密钥校验与安全存储（`grep sk-` 零命中） | ⭐⭐ | 首个体验点 |
| D | `create_agent` 编译图能否被另一图当工具 | ⭐ | 路线已弃，仅历史 |
| E | 9.14 的 A-1~A-7 实验 | ⭐⭐ | A-6 决定 State 写法 |
| F | 真实 LLM 下的审批端到端 | ⭐⭐ | 冒烟 test stub 了 LLM |
| G | LangGraph SQLite saver 的长期可靠性 | ⭐⭐ | M4 实测 |
| H | `old_hash` 乐观锁是否真的能防覆盖 | ⭐⭐ | 当前只写不校验 |

---

## 4. 关键转折

| 时间 | 从 | 到 | 原因 |
|---|---|---|---|
| 2026-09-07 → 09-15 | 子代理=工具（A 路线） | 子代理=子图节点（B 路线） | 需要看内部/打断；B 更可控 |
| 2026-09-08 → 09-14 | `create_agent` + middleware | 手搓 StateGraph | 图结构固定、拿不到结构化 diff、黑盒 |
| 2026-09-06 → 09-16 | 单一后端 | uv workspace 三包 | 双端需求分叉；共享代码下沉 core |
| 2026-09-16 → 10-22 | 审批只靠图中 `pending` | DB 审批表 + 幂等 + 统一执行器（进行中） | 重启后能恢复；防重复执行 |
| 2026-10-22 → 10-23 | 双端共用 `backend/` | 双端独立后端 | 旧代码两份副本会漂移 |

---

## 5. 证据索引

历史文档在合并后已清理；除学习记录外，其余可从 **git 历史**查看。

| 位置 | 内容 |
|---|---|
| `docs/archive/9.*.md` | 2026-09 学习记录（保留，供本人阅读） |
| git 历史 `docs/PLAN.md` | 2026-08-29 规划稿 |
| git 历史 `docs/DESKTOP-PLAN.md` | 桌面版产品定义与里程碑 |
| git 历史 `docs/DEV.md` | 开发环境与命令 |
| git 历史 `docs/NOTES.md` | 踩坑笔记（1025 行） |
| git 历史 `docs/2026-10-22-*.md` | 审批 V1/V2 设计与审查 |
| git 历史 `AI-CHANGES.md` | 逐文件变更台账 |
| git 历史 `docs/2026-09-05-llm-gpu-deploy-summary.md` | 本地 GPU 部署 |

---

## 6. 变更台账（逐文件）

> 原 `AI-CHANGES.md` 的职责并入本节；完整历史见 git。
> 新增改动请追加到本表，并写明**复核重点**。

### 2026-10-24 · 流式桥 + 审批恢复

| 文件 | 改动 | 复核重点 |
|---|---|---|
| `agent/state.py` | `mode` 加默认值 `"code"` | 默认值只是让当前唯一路径能跑；主管图接好后应改为由请求/配置决定 |
| `agent/stream.py` | 重写：`agent_stream` / `agent_resume_stream` / 事件封闭集 / 中断去重 / 挂起兜底 | ① `subgraphs=True` 是实测结论，不是偏好；② 挂起期间新消息选了"不启动新 run"，Q2 拍板后要改；③ 去重只按 interrupt.id |
| `api/contracts.py` | 新增 `AgentResumeRequest` | `review` 直接复用图内 `ReviewDecision`，别在 HTTP 层再抄一份 |
| `api/agent.py` | `GET /resume`（空实现）→ `POST /resume`，404/409 三条判据 | 判据顺序：归属 → 是否挂起 → 决定对齐；漏一条就可能串批 |
| `agent/contracts.py` | `ItemDecision.reason` 补默认 `None` | Pydantic v2 里 `str \| None` 无默认值仍必填，实测导致 /resume 直接 422 |
| `agent/dependencies.py` | diff 头改相对路径（T15）；目录明确报错（T16） | T15 是隐私泄漏面；T16 别把目录当成"新建空文件"审 |
| `apps/desktop/tests/smoke_stream_bridge.py` | 新建 | 用会分块的假模型验证帧序；真模型 token 形状以实测为准 |
| `apps/desktop/tests/smoke_http_resume.py` | 新建 | 真 lifespan + 真 SQLite，CWD 切临时目录 |
| `scripts/experiments/probe_stream_shape.py`、`probe_stream_v3.py` | 新建（探测脚本） | 结论只对 langgraph 1.2.11 成立，升级版本要重跑 |
| `agent/dependencies.py` | 新增 `verify_preview_unchanged`；全批准后执行前比哈希（T14） | ① 只窄化 TOCTOU，未消除；要原子化见 T23；② 新文件按"是否已存在"判冲突；③ 任一冲突整批作废 |
| `apps/desktop/tests/smoke_old_hash.py` | 新建 | 4 种情形：改/建/删/未变 |
| `packages/core/pyproject.toml` | `sqlalchemy` → `sqlalchemy[asyncio]` | 升级到 2.1 后必须带 extra，否则 greenlet 缺失直接 ImportError |
| `agent/nodes/coder.py` | `prepare_node` 进子图先清空 `coder_messages`（T13） | 清空只在子图入口；resume 不经过，别把清空挪到 model_node |
| `apps/desktop/tests/smoke_coder_isolation.py` | 新建 | 断言看“模型实际收到的消息”，不是 state 字段 |
| `uv.lock` | 全量升级 | 帧形状已重验；回滚用 `uv.lock.bak-2026-10-24` |
| `agent/tools/path_jail.py` | 新增 `ensure_sandbox_root()` | 让“配置了沙箱”蕴含“沙箱存在”；创建失败要拒绝启动 |
| `agent/tools/coder_tools.py` | 写工具建父目录；IO 异常走白名单措辞 | ① mkdir 在 `_resolve` 之后，越界到不了；② 新异常类型必须加分支 |
| `main.py` | lifespan ⓪ 步创建沙箱根 | 放在 DB/checkpoint 之前；失败直接 raise |
| `apps/desktop/tests/smoke_tool_safety.py` | 新建 | 断言的是“模型看到的文本”，不是日志 |
| `agent/contracts.py` | `WritePreview.creates_dirs`（T34） | 默认空列表；顺序必须由浅到深，别改成 set |
| `agent/dependencies.py` | `build_write_review` 计算缺失祖先目录 | 只列**尚不存在**的；越界路径在更早的 resolve 已被挡 |
| `task/service.py` | 新增 T18 审批服务 | ① SAVEPOINT 不能换成 try+commit；② 幂等键不含 args_hash；③ `as_utc` 是所有时间比较的前置 |
| `apps/desktop/tests/smoke_approval_service.py` | 新建 T18 测试 | 并发用例依赖 SQLite 写锁，换 PG 要重验错误类型 |
| `task/lifecycle.py` | 新增迁移表 + 纯函数（T19） | 唯一规则来源，别在别处再写一份；终态=空集合 |
| `task/lifecycle_service.py` | 新增生命周期服务（T19） | `transition_pair` 要求 session 无已开启事务；失败一律返回 CONFLICT 表示“未生效” |
| `task/repository.py` | 两个 `transition_*` 加 `commit` + 静态合法性 | 返回 False 同时代表“非法配对”与“CAS 未命中”，需要区分请走 service |
| `apps/desktop/tests/smoke_lifecycle.py` | 新建 T19 测试 | 并发=同进程两 Session；失败注入用 monkeypatch |
| `docs/WHITEPAPER.md` | §5.3 状态描述与枚举对齐 | 审批态无 EXPIRED；取消用 REVOKED |


### 2026-10-23 · 删除旧单体 + 文档合并

| 文件 | 改动 | 复核重点 |
|---|---|---|
| `backend/`（整个目录） | 删除（60 个跟踪文件） | 确认无运行时反向依赖；旧代码可从 git 历史恢复 |
| `backend/knowledge/` → `knowledge/` | 迁移 32 个语料文件 | 未跟踪资产，必须保留 |
| `backend/_*.py` → `scripts/experiments/` | 归档 3 个实验脚本 | 脚本依赖已删除的 `app.*`，不可直接运行 |
| `docs/WHITEPAPER.md` | 新建 | 架构与决策的唯一权威文档 |
| `docs/PROGRESS.md` | 新建 | 进度与证据的唯一权威文档 |
| `docs/TODO.md` | 新建 | 待办的唯一权威文档 |
| `docs/archive/` | 仅保留 11 份 `9.*` 学习记录 | 其余旧文档已清理，可从 git 历史查看 |
| `README.md` | 从空文件补全 | 快速开始命令需实测 |
| `AGENTS.md` | 指向三份新文档 | 变更台账改到 PROGRESS §6 |
| `apps/desktop/.../__init__.py`、`apps/web/.../__init__.py`、`agent/nodes/chat.py` | 仅 docstring 更新 | 无逻辑改动 |

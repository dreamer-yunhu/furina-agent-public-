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

> 2026-10-26 补充（Stage A 已落地，上表第 25 行"主管图业务节点全 NotImplementedError"只对画像/RAG/生成/持久化成立）：
> **意图路由（CHAT / CODE）已跑通** —— `agent/nodes/supervisor.py` + `agent/nodes/chat.py`，
> 入口只传 `task_input`，路由权威位是程序校验后的 `intent`。轮次边界由 `begin_turn_node` 收口。
> 证据：20 个冒烟脚本 **651/651**（含新增 `smoke_supervisor_turns` 29 条）；真实模型端到端
> （`POST /agent` → CHAT 流式 / CODE 审批中断 → `/agent/resume` → 终态一致）已实测。
> 详见 `docs/audit/2026-10-26-StageA-第二轮审计与修复.md`。

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

### 2026-10-24（续四）· T21 审批超时扫描与挂起
- T21-0 审计 + T21-1 ADR（`docs/audit/`），Q1–Q11 全部按建议确认。
- `task/timeout_scanner.py`：`scan_once` / `ScanReport` / `on_suspended` 钩子；
  逐条两段会话（只读校验 → `transition_pair` 同事务迁移）。
- `repository.list_due_pending_approvals`：PENDING + 到期 + **排除两边都已 SUSPENDED 的对**。
  实施时发现：审批超时后仍是 PENDING，不排除会导致有 limit 的扫描饥饿。
- desktop `services/timeout_scanner.py`：lifespan 后台循环、首轮延迟、异常不退出、
  非法配置 clamp + ERROR、`interval=0` 关闭；`/healthz` 暴露 `timeout_scanner`。
- 配置：`APPROVAL_SCAN_INTERVAL_SECONDS`（默认 30）/ `APPROVAL_SCAN_BATCH_SIZE`（默认 50）。
- 实测：`smoke_timeout_scanner.py` 46/46；全量 12 套全绿；lifespan 实测
  `interval=1 → running`、`interval=-5 → disabled`。
- 未验证：跨进程、PostgreSQL、运行时接线（T23）。

### 2026-10-24（续五）· T20 决策服务
- `task/decision_service.py`：`submit_decision` 落库决定；`DecisionOutcome`
  （APPLIED / IDEMPOTENT / CONFLICT / NOT_FOUND / SCOPE_MISMATCH / ILLEGAL_STATE）；
  `DecisionResult` 携带 `approval` 与 `late`。
- 判定顺序：存在 → 归属 → **已有决定优先于终态任务** → 服务端时间/迟到 → CAS → 失败重读分类。
- 事务：单行 CAS，不加锁、不加 `commit=False`；数据库异常原样抛出。
- 不修改 Task/Execution；不接 `/agent/resume`（T23）。
- 实测：`smoke_decision_service.py` 38/38；全量 13 套全绿。
- 未验证：PostgreSQL、跨进程并发、运行时接线。

### 2026-10-24（续六）· T19 变更：受保护的 RUNNING→SUSPENDED
- 触发：T22 Q11=B（DB 已 RUNNING、图恢复失败需要可重试的挂起路径）。
- `lifecycle.py`：新增边 + `GUARDED_*_EDGES` + `SuspendReason`；默认 API 拒绝该边。
- `repository.transition_*` / `lifecycle_service.transition_pair` 增加 `guarded_ok`（默认 False）。
- `lifecycle_service.suspend_after_resume_failure`：要求两者 RUNNING、该 Execution 下所有审批
  `tool_execution_status == NOT_STARTED`；否则拒绝（已开始/UNKNOWN 不可安全重试）。
- 实测：`smoke_lifecycle.py` 74/74（新增 17 条）。

### 2026-10-24（续七）· T22 恢复前校验与成对恢复
- `task/resume_service.py`：`validate_and_resume` / `ResumeOutcome` / `ResumeResult`。
- 校验：存在与归属 → 状态对（WAITING 或 SUSPENDED，且两者一致）→ 批内无 PENDING →
  全部 APPROVED → 工具未开始 → DB 参数快照 → `old_hash` 文件校验 → 成对迁移 RUNNING。
- 迟到批准允许恢复；失败不改状态；CAS 冲突映射为 `ILLEGAL_STATE`（无 CONFLICT 结果）。
- 未接 `/agent/resume`（Q9=A）；图侧绑定（C7）与 checkpoint 校验（C9）留 T23。
- 实测：`smoke_resume_service.py` 26/26；全量 14 套全绿。

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
| `apps/desktop/tests/smoke_lifecycle.py` | ✅ 74/74 | 2026-10-24 |
| `apps/desktop/tests/smoke_resume_service.py` | ✅ 26/26 | 2026-10-24 |
| `apps/desktop/tests/smoke_timeout_scanner.py` | ✅ 46/46 | 2026-10-24 |
| `apps/desktop/tests/smoke_decision_service.py` | ✅ 38/38 | 2026-10-24 |
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

### 2026-10-27 · Codex 原型移植进 React（视觉重构）

> 依据：`C:\Users\l1575\Downloads\furina-codex-ui-demo.zip`（单文件静态原型）。
> 原 HTML 保留在 `frontend/public/codex-demo.html` 供对照；React 工作台按它重构视觉层。
> 本条取代上一条中关于旧视觉样式的描述，功能/路由仍沿用上一条。

| 文件 | 改动 | 复核重点 |
|---|---|---|
| `frontend/src/styles/{tokens,theme,demo,index}.css` | **重写**：原型配色/字体/间距/阴影；新增 `demo.css`；删除 `layout.css`、`components.css`、`pages.css` | ① 默认浅色，深色仍可用；② 字体 14px / Inter + Segoe UI 回退；③ **背景层是 fixed + z-index:0，主区域必须 z-index:1**，否则 DOM 有内容但截图空白（本轮实际踩到） |
| `frontend/src/features/navigation/{SidebarNav,HeaderBar}.tsx` | **重写**：品牌+新建会话+工作区导航+最近会话+底部用户；顶栏面包屑+演示环境+详情面板+主题 | 顶栏不再显示真实连接状态；详情按钮只在有详情内容的路由出现 |
| `frontend/src/features/chat/{ApprovalCard,MessageRow,ConversationHeader,Composer}.tsx` | **重写**：chat-head、user-row/msg/tool-row、approval 卡片、composer | ① 批准/拒绝只改本地状态；② 已处理默认折叠；③ 「已批准」显示「未执行 · 等待真实结果」 |
| `frontend/src/pages/{Chat,Tasks,TaskDetail,ExecutionDetail,Audit,AuditThread,AuditApprovalDetail,Settings,NotFound}Page.tsx` | **重写**：page-title/page-content/thread-card/task-grid/records | 审计搜索/筛选/展开联动；任务为两列卡片；详情页用卡片分区 |
| `frontend/src/pages/{Approvals,ApprovalDetail}Page.tsx` | 旧入口改为跳转 `/audit` | 路由保留，避免两套审批 UI 漂移 |
| `frontend/src/components/ui/{StatusPill,DemoBadge,PageHeader,KeyValueList,ContentSection,PlaceholderTag}.tsx` | 改为 `.tag` / `.page-title` / `.field` / `.thread-card` 结构 | 状态色不替代文本；Demo 标识不隐藏 |
| `frontend/src/layouts/InspectorSlot.tsx` | 改为 `.panel-head` + `.panel-content` | 关闭按钮只影响布局，不代表取消任务 |
| `frontend/src/app/App.tsx` | HeaderBar 去掉 windowRole；ChatPage 不再传 inspector 状态；面包屑/主题由顶栏统一 | ChatPage 按 threadId 重挂载，避免本地 Demo 消息串会话 |
| `frontend/src/hooks/useTheme.ts` | 默认 `light`（对齐原型），仍支持 system/dark | `system` 不写 data-theme；localStorage 不可用时静默降级 |
| `frontend/public/codex-demo.html`、`codex-demo-README.md` | 保留原始静态原型 | 不是 React 入口；仅用于对照 |
| `frontend/src/**/*.test.tsx` | 更新 24 项测试：路由/导航/侧栏折叠/详情/主题/审批卡片 | 审批测试验证「批准 ≠ 执行成功」 |
| `docs/demo/screenshots/*.png`、`frontend/README.md` | 截图按新 React UI 重拍；README 更新视觉层说明 | 截图来自实际运行，不是设计稿 |

**实测（2026-10-27）**：
- `npm run lint` ✅（oxlint 无输出）
- `npm run build` ✅（tsc -b + vite build，62 modules）
- `npm run test` ✅（4 files / 24 tests）
- Playwright（浅色、1280×800 / 1024×720 / 760×900）：无横向溢出；侧栏 244→60px；详情面板 1024 为第三列、≤950 为 300px 浮层
- 审批：点击「批准执行」→ 折叠为「未执行 · 等待真实结果」；展开显示「等待执行」，不显示「执行成功」
- 控制台：0 error
- **关键缺陷修复**：`.slot--background`（fixed, z-index:0）曾盖住主区域，DOM 正常但截图/视觉为空白；已把 sidebar/main/inspector 抬到 z-index:1

**未修改**：后端业务逻辑、审批状态机、数据库模型、API 契约、`src-tauri/`。

**未提交**：本轮改动停留在工作区。

### 2026-10-27 · Codex 风格 UI Demo（基于 F1）

> 视觉层后续已按 ZIP 原型重构，见上一条；本条目保留功能/路由历史。
> 依据：用户《Codex 风格 UI Demo 开工指南》。一句话：把 F1 空状态骨架填成
> **可交互、可截图、明确标注 Demo 数据**的工作台；不接后端、不改审批状态机。
> ⚠️ 参考图未被当前模型读取（不支持图像输入），本轮依据是指南文字 + Codex 公开页面布局原则。

| 文件 | 改动 | 复核重点 |
|---|---|---|
| `frontend/src/demo/types.ts`、`data.ts` | **新建**：会话/任务/Execution/审批/工具/消息的演示数据与查询函数 | ① Demo 类型不得当后端 DTO 复用；② `status` 与 `toolExecutionStatus` 分开；③ 时间用固定字符串，测试/截图可复现 |
| `frontend/src/features/chat/{ApprovalCard,MessageList,MessageRow,ConversationHeader,Composer}.tsx` | **新建**：会话内消息流、工具事件、审批卡片、输入框 | ① 批准/拒绝只改本地状态并标注 Demo；② 已处理卡片默认折叠、可展开；③ 「已批准」必须显示「等待执行」，不能显示「执行成功」 |
| `frontend/src/features/shared/statusMeta.ts` | **新建**：审批/工具/运行状态文案与语气 | 新增状态必须同步四套映射；审批状态与工具状态不得合并 |
| `frontend/src/pages/{Chat,Tasks,TaskDetail,ExecutionDetail,Audit,AuditThread,AuditApprovalDetail,Settings}Page.tsx` | **重写**：Demo 会话、任务列表、审计三级导航、审批决策链、主题设置 | ① 审计以线程为顶层分组；② 任务与 Execution 历史不覆盖；③ 所有页面显示 Demo 标识 |
| `frontend/src/features/navigation/{SidebarNav,HeaderBar}.tsx` | **重写**：最近会话、任务/审计/设置导航、侧栏折叠、详情面板、主题切换 | 侧栏折叠只隐藏文字；详情按钮只在有详情内容的路由显示 |
| `frontend/src/features/inspector/RouteInspector.tsx` | **重写**：会话/任务/执行/审计/审批的详情摘要 | 只展示摘要，不重复中央工作区完整内容 |
| `frontend/src/app/App.tsx`、`router.ts`、`providers/{ThemeProvider.tsx,themeContext.ts}` | 新增 `/audit`、`/audit/:threadId`、`/audit/:threadId/:approvalId`；侧栏/详情/主题状态；ChatPage 按 threadId key 重挂载 | ① 面板开关按 `match.path` 记录，换路由自动回默认；② 主题只有一份 context；③ 新路由不得破坏旧 `/approvals` |
| `frontend/src/components/ui/{Icon,IconButton,StatusPill,DemoBadge,ContentSection}.tsx` | **新建**：内联 SVG 图标、状态胶囊、Demo 标识、分隔线式内容区块 | 不引入 UI 依赖；图标按钮必须有 aria-label；状态色不替代文本 |
| `frontend/src/hooks/useTheme.ts`、`styles/*` | 主题读写 + Codex 风格令牌/布局/组件样式 | ① `system` 不写 `data-theme`；② 中性背景、少阴影、少圆角；③ 窄屏 Inspector 浮层、侧栏收窄 |
| `frontend/src/components/placeholders/*` | 角色入口缩为小圆形；背景改纯色 | 角色不得占用中央工作区 |
| `frontend/src/**/*.test.tsx`、`vitest.config.ts` | 新增/更新 24 项测试：路由、导航、侧栏折叠、详情面板、主题、审批卡片 | 只测纯前端；审批卡片测试必须验证「批准 ≠ 执行成功」 |
| `frontend/README.md` | 更新 Demo 路由、数据边界、测试边界 | 不得把 Demo 写成真实后端能力 |
| `docs/demo/screenshots/*.png` | **新增**：会话页、待审批卡片、审计页、审批详情截图 | 截图来自实际运行，深色主题，1920×889；非设计稿 |

**实测（2026-10-27）**：
- `npm run lint` ✅（oxlint 无输出）
- `npm run build` ✅（tsc -b + vite build，66 modules）
- `npm run test` ✅（4 files / 24 tests）
- Playwright（深色、1920×889）：`#/chat/thread-lab-summary`、`#/audit`、`#/audit/thread-preflight/approval-cleanup-script` 均正常；控制台 0 error
- 审批卡片：点击批准 → 折叠为「已批准」摘要；展开显示「等待执行」，不显示「执行成功」
- 窄屏 760×900：无横向溢出；侧栏收窄到 68px；详情面板改为 352px 浮层
- **未运行**：后端测试、SSE 断连、真实审批恢复、Tauri 窗口/进程测试（属于 F2–F4）

**未修改**：后端业务逻辑、审批状态机、数据库模型、API 契约、`src-tauri/`。

**未提交**：本轮改动停留在工作区。

### 2026-10-27 · 前端 F1：工作台骨架与美术插槽

> 依据：`docs/audit/2026-10-27-前端集成F0-整合审计.md` 与用户提供的 F1 开工指南。
> 一句话：把 Vite 模板替换成**可导航、可换肤、可插槽**的工作台骨架；
> **不接任何后端接口、不写模拟业务数据**。

| 文件 | 改动 | 复核重点 |
|---|---|---|
| `frontend/src/app/router.ts` | **新建**：hash 路由匹配（`matchPath`）、`navigate`、`useHashLocation`、`ROUTE_TITLES` | ① 用 hash 而非 history，因为 Tauri 生产环境不保证未知路径回退 `index.html`；② `navigate` 用 `pushState` + 显式派发 `hashchange`（jsdom 不会自动派发）；③ 同时监听 `popstate`，保证前进/后退 |
| `frontend/src/app/App.tsx` | **新建**：路由 → 页面映射；根路径重定向 `/chat`；Inspector 显隐由路由决定 | 不在这里发请求、不推断任务状态；新增页面只改这里与 `router.ts` |
| `frontend/src/app/Link.tsx` | **新建**：内部链接，拦截普通左键 | 带修饰键/中键的点击交还浏览器 |
| `frontend/src/layouts/*`（7 个） | **新建**：`WorkbenchLayout` + Header/Sidebar/Main/Inspector/Background/Character 插槽 | 布局只管网格、定位、滚动；插槽内容全部由 props 注入；窄屏 Inspector 改浮层、小屏侧栏改横向导航 |
| `frontend/src/pages/*`（8 个） | **新建**：对话/任务/任务详情/执行详情/审批/审批详情/设置/404 | 全部空状态明确写「接口尚未实现」；不生成模拟行；设置页不发起探活 |
| `frontend/src/features/navigation/*`、`features/inspector/*` | **新建**：顶栏、侧栏导航、按路由的详情面板 | 导航项只描述「去哪里」；详情面板只放占位，不伪造执行数据 |
| `frontend/src/components/**` | **新建**：Panel/PageHeader/EmptyState/Notice/KeyValueList/PlaceholderTag/ConnectionStatus/AppBackground/CharacterPlaceholder | `ConnectionStatus` 默认 `unknown`，不得默认显示已连接；占位组件与业务组件分离 |
| `frontend/src/styles/*`（6 个） | **新建**：tokens/theme/layout/components/pages/index | 业务组件只用 `theme.css` 的语义变量；深色模式跟随系统，也可用 `data-theme` 覆盖；布局宽度/层级/安全边距都在 tokens |
| `frontend/src/assets/app/artwork.ts` | **新建**：美术资源集中入口（当前为空） | 换图只改这里；不要引入未授权素材 |
| `frontend/src/services/desktop/windowRoles.ts` | **新建**：F4 双窗口适配缝（`?window=character`） | **当前未接线到 Tauri**；只影响顶栏角色标签，不创建窗口 |
| `frontend/src/services/api/config.ts` | **新建**：`API_BASE_URL` | F1 只在设置页展示，不发起请求；F2 的 API Client 从这里取 |
| `frontend/src/main.tsx` | 改为挂载 `app/App` + 单一 `styles/index.css` | 不要恢复组件内全局 CSS 导入 |
| `frontend/src/test/setup.ts`、`router.test.ts`、`App.test.tsx`、`vitest.config.ts` | **新建**：jsdom 测试，覆盖路由匹配、默认页、侧栏导航、详情参数、404、根路径重定向 | 只测纯前端；不启动后端、不 mock 业务数据 |
| `frontend/package.json`、`tsconfig.node.json` | 新增 `test`/`test:watch` 脚本与 4 个开发依赖（vitest/jsdom/@testing-library/react/@testing-library/jest-dom）；`vitest.config.ts` 纳入 node tsconfig | 测试依赖只在 devDependencies；不改生产依赖 |
| `frontend/README.md` | 更新为 F1 目录结构、命令、设计约束与「未实现」清单 | 不得把 F1 绿灯写成业务链路已验证 |
| 删除 `frontend/src/App.tsx`、`App.css`、`index.css`、`assets/{react.svg,vite.svg,hero.png}` | 移除 Vite 模板示例 | 只删模板演示资源，不动 `src-tauri/`、`vite.config.ts`、`tauri.conf.json` |

**实测（2026-10-27）**：
- `npm run build` ✅（tsc -b + vite build，48 modules）
- `npm run lint` ✅（oxlint 无输出）
- `npm run test` ✅（2 files / 14 tests）
- `npm run dev`（vite 8.3.5，127.0.0.1:1420）✅ HTTP 200，检查后已停止
- **未运行**：任何后端测试、SSE 断连、审批恢复、Tauri 窗口/进程测试（属于 F2–F4）

**未提交**：本轮改动停留在工作区，未执行 `git commit` / `git push`。

### 2026-10-26（第二轮）· Stage A 跨轮状态残留修复

> 依据：`docs/audit/2026-10-26-StageA-第二轮审计与修复.md`（含缺陷 D1~D7 与证据）。
> 一句话：把"按 run 重置 state"从**三个调用方各写一遍**改成**图内的一个轮次起点节点**。

| 文件 | 改动 | 复核重点 |
|---|---|---|
| `agent/state.py` | **新增 `intent_reason: str \| None`**（`max_length=255`）：意图模型 `reason` 的落点 | 消费者只有两个：路由失败并进 `route_error`（用户可见）、成功路由打一条 INFO 日志。**它不是判断依据**，任何分支都不许读它做决策；run 级字段，由 `begin_turn_node` 清空 |
| `agent/nodes/supervisor.py` | **新增 `begin_turn_node`** + `_RUN_SCOPED_NULLABLE`：从 START 进来先重置 `intent/intent_raw/intent_reason/intent_error/route_status/route_error/result/subagent_task` 与 `intent_attempts=0`；`_parse_intent` 返回值改成具名 `ParsedIntent` 并解析 `reason`（`_clean_reason`：缺/空/类型错→`None`，超长截断 255，永不抛异常） | ① **只清 run 级字段**，绝不能加 `messages`；② 重试边直达 `intent_node`、`resume` 从断点继续，都不经过它 —— 这是重试反馈与审批恢复不变的前提；③ 新增运行期字段时记得登记进 `_RUN_SCOPED_NULLABLE`；④ `reason` **不参与校验、不影响重试**，别把它塞进 `format_error` 分支 |
| `agent/build.py` | 接线 `START → begin_turn_node → intent_node`（原 `START → intent_node`） | 图拓扑变了：从 START 重跑旧现场会多走一个节点（生产每次新 thread，无影响）；resume 不走 START，不受影响 |
| `agent/stream.py` | **删除**入口的 `"intent_attempts": 0` | 别加回来 —— 加回来等于恢复"三处各写一遍"的旧结构，D1~D3 就是这么漏出来的 |
| `api/contracts.py` | `AgentRequest.user_input` 加 `min_length=1` + 去空白校验（空白 → 422） | 校验放 HTTP 层（用户错误）；`intent_node` 的 `ValueError` 保留为绕开 HTTP 时的最后断言 |
| `tests/_t23_testkit.py` | 删除 `run_input` 里的 `intent_attempts`；**导入即把意图模型换成 fail-fast 桩**（忘装替身立刻报错，不再静默连网） | 这是测试进程内的副作用，只允许存在于测试专用模块 |
| `tests/smoke_coder_isolation.py` | 去掉手工的 `intent_attempts: 0` | 同上 |
| `tests/smoke_supervisor_turns.py` | **新建**：同一 thread 四种轮次组合 + 重试预算 + `messages` 保留 + `intent_reason` 跨轮，29 条 | 段 2 的"无陈旧反馈"断言只扫 `HumanMessage`（提示词本身含该字样，扫 SystemMessage 会假红） |
| `docs/audit/2026-10-26-StageA-第二轮审计与修复.md` | **新建**：本轮审计与修复记录 | 含 D1~D7、`reason` 占位与消费者、651 项断言复跑结果 |

### 2026-10-26 · Stage A：主管图接入（CHAT / CODE 路由）

> 依据：`docs/audit/2026-10-26-StageA-Phase0-核对报告.md`，实施报告见
> `docs/audit/2026-10-26-StageA-实施报告.md`。

| 文件 | 改动 | 复核重点 |
|---|---|---|
| `agent/state.py` | 删 `mode`；新增 `task_input` / `intent` / `intent_raw` / `intent_error` / `intent_attempts` / `route_status` / `route_error` / `result`；新增 `ChatState`；`CoderState` 加 `result` | ① `mode` 删了不会报错（Pydantic 忽略未知字段），别照抄旧调用；② `intent` 只能由校验节点写 |
| `agent/contracts.py` | 新增 `Intent` 枚举 + `SUPPORTED_INTENTS` | 新增成员 = 新增图路径，必须同步 `supervisor._GOTO` 与 `build.py` |
| `agent/nodes/supervisor.py` | **新建**：`intent_node` / `validate_intent_node` / `route_failed_node` + `_parse_intent` | ① 意图输出只进 `intent_raw`，绝不进 `messages`；② "格式非法"可重试、"合法不支持"不重试；③ 失败节点不碰数据库 |
| `agent/nodes/chat.py` | 重写为 CHAT 子图（`ChatState` + `chat_messages` + `result`）；删掉无人调用的 `make_furina_node` | ① 不挂工具、不需要审批；② `ainvoke` 不影响流式（LangGraph 会强制走 `_astream`） |
| `agent/nodes/coder.py` | 新增 `finish_node` 写 `result`；`should_continue` 末态改指 `finish_node` | 只搬运文本，不调模型、不碰库；审批中断时不会走到这里 |
| `agent/build.py` | 装配 `START → intent → validate →（chat / coder / failed）→ END`；删除 `route_node`/`route_edge` 占位 | 子图节点名同时被 `stream._AGENT_BY_NODE` 与 `supervisor._GOTO` 引用，改名要同步两处 |
| `agent/stream.py` | 入口改传 `task_input`（不再传 `mode`/`subagent_task`）；补 `chat` 归属；主管 token 黑名单；收尾读 `route_status` 判 failed；**按 run 重置 `intent_attempts`** | ① 黑名单只挡 `supervisor`；② 收尾必须区分 interrupted / failed / completed 三种；③ 不重置计数会让重试预算跨 run 累积（核验 F1） |
| `agent/llm.py` | 新增 `supervisor_llm`（`disable_streaming=True`） | 不要改成复用 `llm`，否则意图 token 重新可流式 |
| `agent/dependencies.py` | 新增 `message_text()`（content 可能是 list[dict]） | 只取 `text` 块，别 stringify 整个结构 |
| `agent/prompts/intent.txt` | **新建**：意图分类提示词（只输出 JSON） | 拿不准时判 CHAT（闲聊无副作用）；不要接 `supervisor.txt`（那是元提示词） |
| `apps/desktop/tests/smoke_supervisor_route.py` | **新建**：路由 / 重试 / 不支持 / 契约边界 33 条 | 断言看最终图状态，不看节点返回值 |
| `apps/desktop/tests/smoke_supervisor_stream.py` | **新建**：SSE 归属 + 三类失败落库 22 条 | 假模型**实现 `_astream`** 才是"会漏 token"的真实条件 |
| `_t23_testkit.py` 及 6 个既有测试 | 加 `install_intent()`、输入改 `task_input` | 所有图级测试都必须装意图替身，否则静默连网 |

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
| `task/timeout_scanner.py` | 新增 T21 扫描核心 | 不改 `approval_status`；回调只在 APPLIED 后调用；单条失败不终止整轮 |
| `task/repository.py` | 新增 `list_due_pending_approvals` | 必须排除“两边都 SUSPENDED”的对，否则 limit 饥饿 |
| `services/timeout_scanner.py`（desktop） | 后台循环与启停 | 先 sleep 再扫；非取消异常吞掉并记录；`interval=0` 关闭 |
| `config.py` | 两个扫描配置项 | 负数/非正批量在桌面端 clamp + ERROR |
| `main.py` | lifespan 启停 + healthz | 先停扫描器再关存储 |
| `apps/desktop/tests/smoke_timeout_scanner.py` | 新建 | 用例间需清库，否则到期审批互相污染 |
| `task/decision_service.py` | 新增 T20 决策服务 | 已有决定必须排在终态任务校验之前；数据库异常不映射为 outcome |
| `apps/desktop/tests/smoke_decision_service.py` | 新建 T20 测试 | 并发用例依赖 SQLite 写锁；PG 未验证 |
| `task/lifecycle.py` | T19 变更：加受保护边 + `SuspendReason` + `GUARDED_*` | 受保护边默认拒绝；新增受保护边时必须同步更新集合与专用入口 |
| `task/repository.py` | `transition_*` 增加 `guarded_ok` | 默认 False；低层调用可直接放行，属于受控例外 |
| `task/lifecycle_service.py` | `transition_pair` 增加 `guarded_ok`；新增 `suspend_after_resume_failure` | 专用入口只接受 `RESUME_FAILED`；工具已开始/UNKNOWN 一律拒绝 |
| `task/resume_service.py` | 新增 T22 恢复服务 | 状态对必须一致；迟到允许；CAS 冲突映射 ILLEGAL_STATE；文件校验只读 |
| `apps/desktop/tests/smoke_resume_service.py` | 新建 T22 测试 | 文件测试用临时沙箱；并发=同进程两 Session |


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

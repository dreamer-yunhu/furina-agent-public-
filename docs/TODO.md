# 芙宁娜 Agent 待办记录

> 最后更新：2026-10-23
> 规则：
> 1. **P0 → P3 从上往下做**，不要跳级；每完成一项，把 `[ ]` 改 `[x]` 并补一行证据。
> 2. 每条都必须有**可执行验收判据**；写不出判据的任务，先拆小。
> 3. 设计依据看 [WHITEPAPER.md](WHITEPAPER.md)，历史看 [PROGRESS.md](PROGRESS.md)。

---

## 1. P0 · 端到端阻塞（先做这三件）

### [x] T1 实现 `agent_stream`（LangGraph → SSE 桥）
> ✅ 2026-10-24：`smoke_stream_bridge.py` 37/37、`smoke_http_resume.py` 16/16。
> 实现要点：**必须 `subgraphs=True`**（否则停在 interrupt 时不吐 token），中断按 `interrupt.id` 去重。
- **文件**：`apps/desktop/src/furina_desktop/agent/stream.py`
- **要做什么**：解包 `(mode, payload)`；`messages` 流发 token，`values` 流检测 `interrupts`；事件用封闭集 `token/tool_start/tool_end/approval_required/error/done`。
- **验收**：
  - `POST /agent` 返回 200 且能收到 token 帧；
  - 触发高风险写操作时收到 `approval_required`，载荷含 `path` + `diff` + `interrupt.id`；
  - run 结束事件能区分"正常结束"与"带 pending 中断结束"。
- **依据**：`stream.py:27-56` 的 TODO；WHITEPAPER §3.7。

### [x] T2 实现 `POST /agent/resume`
> ✅ 2026-10-24：`smoke_http_resume.py` 16/16（404 未知线程 / 409 未挂起 / 409 决定不匹配 / 200 落盘）。
- **文件**：`apps/desktop/src/furina_desktop/api/agent.py:44-46`
- **要做什么**：接收 `ReviewDecision`，校验线程归属与"图确实处于 interrupt"，再 `Command(resume=...)`。
- **验收**：
  - 批准后沙箱文件出现且内容正确；
  - 拒绝后文件不出现，且模型收到打回消息；
  - 对非挂起线程 resume 返回 409，不执行任何工具。
- **依据**：`api/agent.py`；PROGRESS §0。

### [x] T3 修 `mode` 必填导致的首次调用失败
> ✅ 2026-10-24：`SupervisorState.mode` 默认 `"code"`，`agent_stream` 也显式传。
- **文件**：`agent/state.py:27`、`agent/stream.py:32`
- **要做什么**：二选一——给 `mode` 默认值，或在 `agent_stream` 构造输入时显式传入。
- **验收**：修好 T1 后，第一次 `POST /agent` 不再抛 `ValidationError`。
- **依据**：`SupervisorState.mode` 是 `Literal` 无默认值；`stream.py` 只传了 `messages`。

---

## 2. P0 · M0 三个未验证假设（决定产品形态）

### [ ] T4 验证假设 A：Python 后端能打包成可执行文件
- **做法**：最小 FastAPI 服务 → PyInstaller/Nuitka → 在**没装 Python** 的 Windows 机器运行。
- **验收**：陌生机器双击能起服务并响应 `/healthz`。
- **不成立的后果**：退回"本地 Web 应用"形态（用户装一次、浏览器打开）。
- **依据**：DESKTOP-PLAN §2 假设 A（已归档）。

### [ ] T5 验证假设 B：Tauri 能可靠管理 Python 子进程
- **验收**：拉起 → 探活 → 正常退出回收 → 强杀后无僵尸 → 启动时清理残留。
- **依据**：DESKTOP-PLAN §2 假设 B。

### [ ] T6 验证假设 C：密钥校验与安全存储
- **做法**：保存前发一次最小请求；同时发一个带 `tools` 的请求判断是否支持工具调用；日志降级为 INFO 并静默第三方库。
- **验收**：错误密钥在"保存那一刻"就报可操作提示；`grep -r "sk-" 日志` 零命中。
- **依据**：DESKTOP-PLAN §2 假设 C、§5.3。

---

## 3. P1 · 主管图（没有它就不是完整产品）

### [ ] T7 拍板："LLM 生成节点"与"主管"是不是同一个节点
- **为什么要先做**：这个不定，主管图装配写不下去（`build.py:20-21` 自己写着未决）。
- **验收**：在 WHITEPAPER 的 ADR 表里补一行决策 + 理由 + 代价。

### [ ] T8 实现 `profile_node`（用户画像注入）
- **文件**：`agent/build.py:33-42`
- **验收**：`user_name` / `personal_preference` 能写进 state，且不把 ORM 对象塞进去。
- **依据**：字段已就位，只差写入。

### [ ] T9 实现 `route_node` + `route_edge`（意图路由）
- **文件**：`agent/build.py:45-61`
- **要做什么**：规则优先、LLM 兜底、默认闲聊；返回字符串必须与条件边映射表逐字一致。
- **验收**：三类输入（闲聊 / 需检索 / 需工具）各走对分支。

### [ ] T10 实现 `rag_node`（RAG 检索）
- **文件**：`agent/build.py:64-72`
- **要做什么**：先做占位实现（返回空），不要阻塞整图；接口固定为 `retrieve(query, domain)`。
- **验收**：图能跑通；后续换 LanceDB 只改一个文件。

### [ ] T11 实现 `generate_node`（LLM 生成 + 流式）
- **文件**：`agent/build.py:75-82`
- **验收**：按 `mode` 切换人设；SSE 能收到流式 token。

### [ ] T12 实现 `persist_node` + 完成图装配
- **文件**：`agent/build.py:85-109`
- **验收**：主管图完整跑一轮（用户输入 → 路由 → 生成 → 持久化）；重启后历史还在。

---

## 4. P1 · 正确性与状态

### [x] T13 清空 `coder_messages` 的跨轮残留
> ✅ 2026-10-24：`prepare_node` 用 `RemoveMessage(REMOVE_ALL_MESSAGES)` + 本轮任务；`smoke_coder_isolation.py` 7/7。
> 边界：只在子图入口清空，resume 不经过该节点。
- **问题**：`add_messages` 是追加语义，`prepare_node` 只 append 不清理 → 第二次调 coder 带上一轮消息。
- **做法**：进入子图时用 `RemoveMessage` 清空（先确认 LangGraph 当前版本机制）。
- **验收**：同 thread 连续两次调 coder，第二次的初始消息只有本次任务。
- **依据**：`9.14` A-7 预测；`coder.py:32-39`。

### [x] T14 落地 `old_hash` 乐观锁
> ✅ 2026-10-24：`dependencies.verify_preview_unchanged` + `handle_review_fn` 执行前校验；`smoke_old_hash.py` 8/8。
> 注意：只窄化竞态窗口，未消除（校验到 ToolNode 落盘仍有间隙，见 T23）。
- **问题**：`WritePreview.old_hash` 只写不校验；审批期间文件被改仍会覆盖。
- **做法**：执行前重新读取文件、比对哈希；不一致则拒绝执行并回填消息。
- **验收**：审批挂起期间修改目标文件 → 批准后不覆盖，模型收到"文件已变化，请重新审批"。

### [x] T15 修 diff 头泄漏绝对路径
> ✅ 2026-10-24：`build_write_review` 改传 `Path(rel_path).as_posix()`；冒烟断言 diff 里无 `C:\`。
- **文件**：`dependencies.py:131`
- **做法**：`make_diff` 的 `fromfile/tofile` 传沙箱相对路径。
- **验收**：`diff` 字段中不出现 `C:\` 或沙箱根路径。

### [x] T16 修目录被误判为新文件
> ✅ 2026-10-24：`target.exists() and not target.is_file()` → `ValueError`，经 prevalidate 回填模型。
- **文件**：`dependencies.py:122-129`
- **验收**：目标是目录时返回明确错误，不构造写预览。

### [ ] T17 实现或删除 `rollback_tool_messages`
- **现状**：空函数体 `pass`（`dependencies.py:261`）。
- **验收**：要么有调用者且有测试，要么删除。不要留悬空 API。

---

## 5. P1 · 审批 V2 阶段 B / C

> 设计要点见 WHITEPAPER §5.3 与本节；完整方案可从 git 历史查看（旧文档已清理）。

### [x] T18 create-or-get 幂等创建
> ✅ 2026-10-24：`furina_core/task/service.py`（`create_or_get_approval` / `canonical_args_json` / `compute_args_hash` / `derive_idempotency_key` / `as_utc` / `ApprovalConflict`）；`smoke_approval_service.py` 33/33，`smoke_task_models.py` 仍 21/21。
> 已按审计拍板：Q1 键不含 args_hash、Q2 冲突抛错、Q3 UTC 归一化、Q6 服务层跨任务校验；未改 schema 与 repository 接口。
- **做法**：`SAVEPOINT` + `IntegrityError` + `args_hash` 语义校验。
- **验收**：同一 `idempotency_key` 并发创建只落一行。

### [x] T19 Task / Execution 生命周期服务
> ✅ 2026-10-24：`task/lifecycle.py`（迁移表 + 纯函数）、`task/lifecycle_service.py`（TransitionOutcome / 成对迁移 / 创建入口）、repository 两个 `transition_*` 加 `commit` 与静态校验；`smoke_lifecycle.py` 55/55。
> 并发口径：同一进程、两个独立 Session；跨进程与 PG 未验证。
> 📋 审计报告：`docs/audit/2026-10-24-T19-0-审计报告.md`（现状事实、迁移表现状 vs 提案、事务边界实测、测试缺口、Q1–Q8 待拍板）
- **验收**：状态迁移只能按状态机走；非法迁移返回明确错误。

### [x] T20 审批决定服务（服务端时间 / 幂等 / 冲突）
> ✅ 2026-10-24：`task/decision_service.py`（`submit_decision` + `DecisionOutcome` + `DecisionResult`）；`smoke_decision_service.py` 38/38。
> ⚠️ 原验收写“过期决定不生效”，与 T20-0 拍板 Q4（允许保存迟到决定，仅用于分类）冲突；已按拍板执行，并在 ADR 记录。
> 不修改 Task/Execution（恢复属 T22）；不做运行接线（T23）。
- **验收**：决定使用服务端时间与 `deadline_at` 比较；过期决定不生效。

### [x] T21 超时扫描协程
> ✅ 2026-10-24：`task/timeout_scanner.py`（scan_once/ScanReport/回调）+ `list_due_pending_approvals` + desktop 后台循环与配置；`smoke_timeout_scanner.py` 46/46。
> 超时只置 Task/Execution `SUSPENDED`，审批保持 `PENDING`；查询排除已挂起对以防 limit 饥饿。
> 未验证：跨进程、PostgreSQL、运行时接线（等 T23）。
- **验收**：超时只把 Task/Execution 置 `SUSPENDED`，**不改审批状态**。

### [ ] T22 迟到批准 + 恢复前校验
- **验收**：线程归属、图处于 interrupt、批内无 pending、batch 一致；任一不满足返回 409。

### [ ] T23 统一执行器，把高风险工具移出 ToolNode
- **现状**：`ToolNode(coder_tools)` 含高风险工具（`coder.py:62`）。
- **验收**：高风险工具只能经"DB 审批校验 + 执行器"执行；未审批调用无法落盘。

### [ ] T24 最小 `supervisor_node` + 重委派
- **验收**：校验失败 → 结构化结果 → 主管建新 Task；`redelegation_key` 唯一，重复不建。

### [ ] T25 图接 `task_id / execution_id / graph_thread_id`
- **现状**：LangGraph 运行键仍是业务 `chat_thread_id`（`stream.py:33`）。
- **验收**：一次执行使用独立的 `graph_thread_id`；同线程多任务不串状态。

---

## 6. P2 · 清理与技术债

### [ ] T26 清理死代码
- `is_legal_args`（无调用点）
- `rollback_tool_messages`（空壳，见 T17）
- `ToolRisk` 枚举（无人使用）
- **验收**：grep 确认无调用后删除，或补上调用者与测试。

### [ ] T27 落地 `AgentResult` / `AgentError` 契约
- **现状**：白皮书 §5.2 有定义，代码里不存在。
- **验收**：子代理返回结构化结果；主管能据此重试/换招/上报。

### [ ] T28 去掉模型名与 `base_url` 硬编码
- **验收**：从配置读取；首次运行配置页可填。

### [ ] T29 写 thread 状态转储脚本
- **用途**：读 `thread_id` → 打印挂起状态。既是调试工具，也是开源用户的自白书。
- **验收**：能看出"图挂在哪个 interrupt 上"。

### [x] T34 审批载荷补 `creates_dirs`
> ✅ 2026-10-24：`WritePreview.creates_dirs` + `build_write_review` 计算；`smoke_tool_safety.py` 25/25、`smoke_stream_bridge.py` 38/38（字段穿过 interrupt/SSE）。
- **背景**：`WriteFileTool` 现在会自动建父目录（2026-10-24），但审批 diff 里看不出来。
- **做法**：`WritePreview` 加 `creates_dirs: list[str]`，`build_write_review` 计算缺失的父目录。
- **验收**：批准 `sub/dir/x.txt` 时，载荷明确列出 `["sub", "sub/dir"]`；无缺失时为空列表。

### [ ] T30 补 `.env.example`
- **验收**：新 clone 的人知道要填什么，不依赖私有 `.env`。

---

## 7. 测试与工程

### [x] T31 复跑全部冒烟测试
> ✅ 2026-10-24：approval 15/15、checkpoint 14/14、task_models 21/21、core 86/86，新增 bridge 37/37、http 16/16。
- **命令**：
  ```powershell
  .\.venv-build\Scripts\python.exe apps\desktop\tests\smoke_approval_flow.py
  .\.venv-build\Scripts\python.exe apps\desktop\tests\smoke_checkpoint.py
  .\.venv-build\Scripts\python.exe apps\desktop\tests\smoke_task_models.py
  .\.venv-build\Scripts\python.exe packages\core\tests\smoke_public_api.py
  ```
- **验收**：全部通过，并把结果写回 PROGRESS §2。

### [ ] T32 引入 pytest（或明确不引入）
- **现状**：只有纯标准库冒烟脚本。
- **验收**：二选一拍板；若引入，`pytest` 能发现现有 tests。

### [ ] T33 CI（GitHub Actions）
- **验收**：push 后自动跑 import + 冒烟测试。

---

## 8. 需要你拍板（未决）

| # | 问题 | 当前倾向 |
|---|---|---|
| Q1 | 审批粒度：整批拒绝 vs 逐条执行 | 文档推荐逐条；现状整批 |
| Q2 | 挂起期间新消息：返回 409 vs 作废旧 pending | 9.8 铁共识 3 倾向后者 |
| Q3 | `old_hash` 不符时：failed + cancelled？ | 待定 |
| Q4 | 默认审批超时 | 建议 15 分钟 |
| Q5 | 重委派上限 | 建议 3 次 |
| Q6 | 现在引入 Alembic？ | 下次改列前必须 |
| Q7 | 同线程多 Task 并发？ | 待定 |
| Q8 | 同步执行 vs 调度队列 | 待定 |
| Q9 | `mode` 放 `configurable` 还是 State | 会话级 → configurable |
| Q10 | `subagent_task` / `internal_messages` 生命周期与清空点 | 待定 |
| Q11 | 中断事件里的 `agent: "coder"` 归属由谁写 | 待定 |

---

## 9. 触发式（条件满足才做）

- [ ] **全 Rust 迁移**：当 ReAct 循环 ✅、工具执行器、消息合并、工具 schema 生成**四样全部手写**时再评估。当前 1/4。
- [ ] **ADT（手搓 Rust 式枚举）**：当出现第二种形状完全不同的审批载荷（如 shell 命令审批）时再做。用 Pydantic 判别联合，不要 `@dataclass`。
- [ ] **Rust 网关 / Rust RAG**：先用压测数字证明必要，再写。
- [ ] **Alembic**：下次修改已有表列之前必须引入。

---

## 10. 已完成（近期）

- [x] 删除旧单体 `backend/`，语料迁 `knowledge/`（2026-10-23）
- [x] 文档合并为 WHITEPAPER / PROGRESS / TODO（2026-10-23）
- [x] 审批链路 B1–B9 修复（2026-09-30）
- [x] V2 阶段 A 三表持久化（2026-10-22）
- [x] uv workspace 重构（2026-09-16）

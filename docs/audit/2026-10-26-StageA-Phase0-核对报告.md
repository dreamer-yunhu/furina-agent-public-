# Stage A · Phase 0 核对报告 —— 主管图集成

> 性质：**只读审计**。本阶段未修改任何代码。
> ⚠️ 本文所有行号均指基线 `ae87ca6`；实施后行号已发生位移，请以代码为准。
> 核对时间：2026-10-26
> 基线：见下（文档称 `furina-agent-T23-2026-10-24`）
> 依据：`D-SUP-01` ~ `D-SUP-09`、AGENTS.md「先实测，再断言」

---

## 0. 一句话结论

现有 T23 底座（Task/Execution、审批、恢复、SSE）**可用且回归全绿**；缺的是主管图本身。
但有一处会**静默出错**的地方必须先修：`stream.py` 把「图跑到 END」直接判为 `completed`，
路由失败会被写成任务成功。另有一个与直觉相反的实测结论：**主管意图节点只要用 `ainvoke`
就会把内部 token 漏给前端**（机制见 §4-R4），D-SUP-08 要求的隔离必须显式做。

---

## 1. 基线核对（实测，非静态推断）

### 1.1 代码基线

| 项 | 实测 |
|---|---|
| HEAD | `ae87ca6` · 2026-10-24 21:10 · `feat(agent): 打通持久化审批与 LangGraph 恢复链路` |
| tag | **无任何 tag**（`git tag` 为空）→ 文档里的 `furina-agent-T23-2026-10-24` 是**称呼**，不是可回退的锚点 |
| 已跟踪文件改动 | 无（工作树干净） |
| 未跟踪 | `1.py`（练习脚本）、`dist/`、`docs/architecture/`（HITL 图）、`scripts/experiments/_demo_prompt.py`、`_exp_a6.py`、`_t_review.py` |
| 图结构 | `build_graph(InMemorySaver())` → nodes = `['__end__', '__start__', 'coder_graph']` |

> 建议开工前给基线打 tag（`git tag furina-agent-T23-2026-10-24`），否则「改坏了能不能回到基线」只能靠记 commit。

### 1.2 回归基线（今天实跑，全部通过）

| 脚本 | 结果 |
|---|---|
| `apps/desktop/tests/smoke_stream_bridge.py` | 38/38 |
| `apps/desktop/tests/smoke_coder_isolation.py` | 7/7 |
| `apps/desktop/tests/smoke_approval_flow.py` | 15/15 |
| `apps/desktop/tests/smoke_t23_approval_runtime.py` | 29/29 |

跑法：`.venv-build\Scripts\python.exe apps\desktop\tests\<name>.py`（仓库根，控制台中文乱码不影响 PASS/FAIL 判定）。

**这是 Phase 5「没有破坏既有功能」的对照基准。**

---

## 2. 与 D-SUP-01 ~ 09 的逐条差异

### D-SUP-01 意图范围 —— ❌ 全缺

现状：无 `intent` 字段。只有 `SupervisorState.mode: Literal["roleplay","code"] = "code"`
（`agent/state.py:32`）。`roleplay` 是"人设模式"，不是 "CHAT/CODE" 的意图；`code` 也不是意图值。
差异：需新增受约束的 `intent`，并让它成为条件边的**唯一**依据。

### D-SUP-02 产生/校验分离 —— ❌ 全缺

`route_node` / `route_edge` 仍是 `raise NotImplementedError`
（`agent/build.py:45-52`、`:55-61`），且**未注册进任何图**；`build_graph` 只有
`START → coder_graph → END`（`:103-109`）。
差异：意图识别节点、程序校验节点、重试上限、失败出口，四样都要新建。

### D-SUP-03 复用 T23 —— ✅ 已天然满足

- `api/agent.py:153` 每次 `POST /agent` 先 `runtime.start_run(...)` → 建 Task + Execution；
- 图现场键统一取 `run.graph_thread_id`（`agent/stream.py:235`、`:61`）；
- 节点侧经模块级 provider 取 runtime（`agent/runtime.py:794-797`），ORM 不进 state。

→ CHAT 只要走同一条 `agent_stream`，生命周期自动共享，**不需要新增任何持久化代码**。
约束：主管节点里不得出现 `session` / `finalize_run`。

### D-SUP-04 `mode` 不是正式约束 —— ⚠️ 需迁移

全部引用（`rg -n '\bmode\b'` 去噪后）：

| 位置 | 性质 |
|---|---|
| `agent/state.py:32` | 定义（唯一权威位） |
| `agent/stream.py:261` | 每次请求显式写死 `"code"` |
| `apps/desktop/tests/_t23_testkit.py:55` | 测试夹具 |
| `apps/desktop/tests/smoke_coder_isolation.py:84` | 测试夹具 |
| `apps/desktop/tests/smoke_t23_approval_runtime.py:145,173,259,308,360` | 测试夹具（5 处） |
| `scripts/experiments/probe_stream_v3.py:90`、`probe_stream_shape.py:71` | 归档探测脚本 |
| `agent/build.py:50,79`、`agent/stream.py:257` | 仅注释 |

**关键实测**：`SupervisorState` 是 Pydantic `BaseModel`，默认 `extra="ignore"` ——
字段删掉后，旧输入里的 `"mode"` 会被**静默丢弃，不报错**。
所以"删字段"不会炸，但也意味着**没人会发现它已经被删**；必须同时清掉测试夹具里的 key，
否则下一个人读代码会以为 `mode` 仍然是有效输入。

### D-SUP-05 主管/子图独立契约 —— ⚠️ 部分缺失

现状：`SupervisorState` 与 `CoderState` **靠同名字段**传递：
`task_id` / `execution_id`（`state.py:45-46` ↔ `:67-68`）、`subagent_task`（`:41` ↔ `:65`）。
这是子图挂载后 LangGraph 的字段映射机制，**不能随手改名**。

差异：
1. `subagent_task` 现在由 `stream.py:262` 直接等于 `user_input`；
   一旦有了路由，它必须由「主管输入 → 子图输入」的显式映射产生，
   否则 CHAT 的输入也会被塞进 coder 的任务字段（语义漂移且不报错）。
2. 缺 `task_input`（用户原始请求的唯一权威位）。
3. 缺普通子图结果位（`result` / `error`）。

### D-SUP-06 生命周期 vs 业务结果 —— 🔴 当前是错的

`stream.py:200-204`：

```python
snapshot = await graph.aget_state(config)
status = "interrupted" if snapshot.interrupts else "completed"
await _notify_finished(on_finished, status)
```

→ **图只要跑到 END 就是 `completed`**，`runtime.finalize_run` 会把 Task/Execution 成对迁到
`COMPLETED`（`runtime.py:735-744`）。路由失败若只是"结束得早"，数据库会记成功。
这正是验收 A-5 / B-4 要挡的那类静默错误。必须先引入业务态，再谈路由。

### D-SUP-07 审批与恢复 —— ✅ 链路完整，但存在**结构性依赖**

已具备：审批落库（`coder.py:209-247`）、`interrupt()`（`:271`）、checkpoint、
恢复三段校验（`api/agent.py:241-320`）、`preflight_resume` 双向核验（`runtime.py:475-595`）。

🔴 **依赖点**：`preflight_resume` 用 `_iter_snapshots(...)` 深度遍历子图，从
`coder_messages` 里取 `tool_calls` 做参数快照比对（`runtime.py:572-581`）。
它成立的前提是 **coder 以"子图节点"形式挂载**。
→ 任何"为了拿结构化结果而把子图改成普通函数调用"的做法（D-SUP-08 已禁止）会让这里
退化成 `state_mismatch`，且是运行时才炸。

### D-SUP-08 SSE —— ⚠️ 三处需处理

现状：事件封闭集 6 种（`stream.py:42`）；归属映射 `_AGENT_BY_NODE = {"coder_graph": "coder"}`
（`:45`）；`subgraphs=True` + 三模式；中断按 id 去重（`:207-220`）。

1. 🔴 **意图 token 会泄漏**（实测，详见 §4-R4）。
2. 🟡 **归属映射未覆盖 chat**：`_agent_of` 对未登记节点返回「节点名前缀」
   （`:69`），chat 子图不登记就会把 `agent` 发成 `chat_graph`，前端契约不稳定。
3. 🟡 `updates` 分支硬编码读 `update.get("coder_messages")`（`:170`）。
   CHAT 若有自己的消息字段，这里是空跑（无害），但**必须写进契约**，
   不能让后来的人以为"所有子图都有 coder_messages"。

### D-SUP-09 未来扩展 —— ✅ 未越界

`profile_node` / `rag_node` / `generate_node` / `persist_node` 仍是占位
（`build.py:33-91`）且**未注册**。本阶段保持不动。

---

## 3. 最小修改文件清单

| 文件 | 职责 | 规模 |
|---|---|---|
| `agent/state.py` | 加 `intent` / `intent_error` / `intent_attempts` / `task_input` / `route_status` / `result`；删 `mode` | 小 |
| `agent/contracts.py` | 新增 `Intent` 枚举 + 意图结构化契约（含"合法但不支持"的区分） | 小 |
| `agent/nodes/supervisor.py`（新） | `intent_node`（模型）/ `validate_intent_node`（程序）/ 失败出口 | 中 |
| `agent/nodes/chat.py`（改） | 接 ChatState、产出 `result` | 小 |

> 实施偏差（2026-10-26 核验）：`make_furina_node` 工厂**没有保留** ——
> 改为模块级 `chat_llm`，与 coder 的 `llm_with_tools` 一致，测试注入手法统一。
> 该工厂全项目无调用者，保留即死代码。
| `agent/build.py` | 装配：`START → intent → validate →（chat / coder / retry / failed）→ END` | 中 |
| `agent/stream.py` | 输入改 `task_input`；token 来源过滤；done 状态读 `route_status`；chat 归属 | 中 |
| `agent/prompts/intent.txt`（新） | 意图分类提示词 | 小 |
| `apps/desktop/tests/` | 新增 `smoke_supervisor_route.py`；改 `mode` 夹具（7 处） | 中 |

**明确不动**：`agent/runtime.py`、`api/agent.py`、`api/contracts.py`、`packages/core/task/*`、
`agent/nodes/coder.py` 的图结构。

> ⚠️ `agent/prompts/supervisor.txt`（3.8 KB）**不是**意图分类提示词 ——
> 它是写给我（AI 编程助手）的元提示词（"你是我的 AI 编程助手，同时也是我的工程导师…"）。
> 不要复用它做意图识别，也不要把它接进图。

---

## 4. 风险点（按严重度）

### R1 🔴 「END = 成功」误判（D-SUP-06）
位置：`stream.py:200-204`。触发输入：任何路由失败但图正常结束的 run。
后果：Task/Execution 落 `COMPLETED`，前端看到 `done: completed`。
修法：业务态字段 + 收尾时读取；不要靠"有没有异常"判断。

### R2 🔴 意图输出污染对话历史
若 `intent_node` 把模型输出写进 `messages`，下一次 chat/coder 会把
`{"intent":"CHAT"}` 当成对话内容。必须写进独立字段（`intent_raw`）。

### R3 🔴 子图挂载方式变更会打断恢复预检
见 D-SUP-07。判据：`runtime.py:572-581` 还能从子图快照里取到 `coder_messages`。

### R4 🔴 意图节点会漏 token —— **实测结果与直觉相反**
- 探针 A（假模型只实现 `_generate`，无 `_astream`）→ `messages` 流只发 1 条完整 `AIMessage` → 当前 `stream.py` 丢弃 → 不泄漏。
- 探针 B（假模型实现 `_astream`，模仿 `ChatOpenAI`）→ `ainvoke` 也发 `AIMessageChunk` → **会泄漏**。

机制（读了源码）：LangGraph 挂了一个 v2 流式回调，`BaseChatModel._agenerate_with_cache`
判断 `_should_use_protocol_streaming(...)`（`langchain_core/language_models/chat_models.py:587-643`），
只要子类实现了 `_astream` 就走流式桥 —— **与调用方写 `ainvoke` 还是 `astream` 无关**。
`ChatOpenAI` 实现了 `_astream`（`langchain_openai/chat_models/base.py:2159`）→ 真模型同样会流式。

→ "意图节点用 ainvoke 就不会漏"是**错的**。必须显式处理，两层都做：
① 意图用独立 LLM 实例并设 `disable_streaming=True`（源码 `:525-547`，该开关是硬关闭）；
② `stream.py` 只转发**允许来源**的 token（按 namespace / `langgraph_node` 判定）。

*未验证*：真 `ChatOpenAI` 的这一步是推断（依据是源码路径 + 探针 B 的同构模型），
Phase 1 用真模型做一次 30 秒验证即可定案。

### R5 🟡 重试无上限 / 分类错误
"JSON 不合法" 可重试；"JSON 合法但 intent 不在支持集"（如 `RAG`）必须**立即失败**，
不能用同一套重试逻辑（会变成无意义空转）。需要两个不同的出口码。

### R6 🟡 Pydantic 静默忽略未知字段
删 `mode` 后旧调用不报错（见 D-SUP-04）。必须同期清理测试夹具，并保留一行
"已废弃，由 intent 取代"的记录，否则属于无声漂移。

### R7 🟡 resume 会重跑主管节点吗？
语图上不会（checkpoint 停在子图内部），但 `SupervisorState` 新增字段后，
旧 checkpoint 里没有这些字段 —— 恢复时读到的是缺失值。
必须验证：**恢复不依赖 `intent` 等新字段**（子图内部只用 `task_id` / `execution_id` / `subagent_task`）。

---

## 5. 测试计划（与阶段对应）

### Phase 1（路由闭环）
用假 LLM（沿用 `coder_mod.llm_with_tools` 的 monkeypatch 手法），不碰网络：

| 用例 | 期望 |
|---|---|
| intent 合法 = `CHAT` | 进 chat，**不**建第二个 Task/Execution |
| intent 合法 = `CODE` | 进 coder（既有 4 个 smoke 全绿即为证据） |
| 非法 JSON ×2（重试耗尽） | `route_status=failed`，Task = `FAILED`，非 `COMPLETED` |
| 非法 JSON 一次后合法 | 第二次成功路由，`intent_attempts=2` |
| intent = `"RAG"`（合法但不支持） | **不重试**，立即 failed，错误码区分 |

### Phase 2（契约）
- coder 实际收到的 `subagent_task` == `task_input`（看模型输入，不看 state 字段）
- chat 子图内不存在 `coder_messages`；主管 state 里不出现 `chat_messages`
- `route_failed` 有真实生产者与消费者（DB 状态），不是硬编码常量

### Phase 3（SSE）
- chat token 的 `agent == "chat"`
- 意图节点产生 **0 条** token 帧（探针 B 场景的回归）
- `tool_start` / `tool_end` / `approval_required` 仍各 1 次
- 恢复后沿用原 checkpoint（`graph_thread_id` 不变）

### Phase 4（失败路径）
6 类：格式非法 / 重试耗尽 / 合法不支持 / CHAT 模型异常 / CODE 图异常 / 审批中断与恢复。
每类都要断言**数据库最终状态**，不只断言 SSE 帧。

### Phase 5（回归）
§1.2 的四个脚本 + 新增脚本全绿；`git diff` 逐条过目。

---

## 6. 需要拍板的三件事

**Q1 · CHAT 是否独立子图？**
建议：**是**。`ChatState{chat_messages, task_input, result}`，与 coder 对称；
归属由 namespace 判决，`_AGENT_BY_NODE["chat_graph"] = "chat"`。
代价：多一个 state 类 + 一个 3 节点小图（约 40 行）。
替代方案（chat 直接挂在主管图上）：省 40 行，但 token 归属只能靠节点名，且 chat 内部消息会
直接写进 `SupervisorState.messages`，边界变模糊。

**Q2 · V1 要不要给 CODE 子图补 `result`？**
建议：**不做**。当前没有任何消费者（主管不读 coder 结果，前端只用 SSE 文本）。
按 AGENTS.md「只做有调用者的修改」，加一个没人读的字段等于给空房子挑窗帘。
等主管需要"根据子图结果继续决策"（V2 父子任务）时再加。

**Q3 · `mode` 删还是留？**
建议：**删**，并同期清掉 7 处测试夹具里的 `"mode": "code"`。
留着 deprecated 会让下一个人误以为它还是有效输入（R6）。

---

## 7. 未验证 / 待补

1. 真 `ChatOpenAI` 下"主管节点是否漏 token" —— 待 Phase 1 用真模型验证（R4）。
2. 新增主管节点后 `Command(resume=...)` 能否照旧穿透到 coder 子图内部 —— 待 Phase 1 用既有
   `smoke_stream_bridge.py` 的恢复段验证（**不通过就不许进 Phase 2**）。
3. 旧 checkpoint（无 `intent` 等新字段）在恢复时的行为（R7）。

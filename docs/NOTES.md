# furina-agent 踩坑与知识点笔记

> 记录日期：2026-08-29 ｜ 主题：PATCH /users/me 接口修复 + 异常体系 + Pydantic
> 状态：接口已从"必崩"修到"能通"（静态核对通过，尚未跑通验证）

---

## 一、Update 接口修复：踩过的 7 个坑

| # | 坑 | 后果 | 教训 / 知识点 |
|---|---|---|---|
| 1 | async 函数没 `await` | 返回 coroutine 对象，序列化崩 | async 调用链必须**层层 await 到底** |
| 2 | 实参顺序和形参不匹配 | 参数错位，service 里 `user.id` 崩 | 位置参数**必须一一对应**；对照已有正确调用检查 |
| 3 | `session.refresh(stmt)` 传 Update 语句 | `InvalidRequestError` | `refresh()` 只接收 ORM 实例；bulk update 后没实例可刷，直接 commit 即可 |
| 4 | schema 字段名 ≠ 列名 | `Entity 'User' has no property 'username'` | 契约名和列名需要翻译（dict 重组 / Pydantic alias / 全用列名） |
| 5 | 访问不存在的属性 `inform.user_name` | `AttributeError` | 只访问模型**声明过**的字段 |
| 6 | 用 `update_dict.get("user_name")` 反查 | 只改 hobby 时取到 None → 崩 | 反查用**恒存在的字段**（`user_id` 主键），别依赖可能不出现的键 |
| 7 | `return result.update({...})` | 返回 `None`（前端收 null） | `dict.update()` 是 in-place，返回 None；直接构造 dict 返回 |

**接口最终链路（已验证静态通过）**：
```
PATCH /users/me {"username":..,"hobby":..}
  → UserUpdate(alias) 校验（null/空串/空格全挡）
  → model_dump(exclude_unset=True) → 字段名 = 列名
  → 空 dict → 400
  → 查重（排除自己）→ 409
  → user_reset: bulk update → commit → get_user_by_id 反查 → 返回 {"username","hobby"}
  → router 直接 return，FastAPI 自动 JSON
```

---

## 二、异常体系知识点

### 机制
- `@app.exception_handler(...)` = 往"分工表"里加一行。
- FastAPI 拿到异常 → **沿异常类型的继承链从子类往父类爬 → 第一个注册了处理器的类，就用它的处理器**（具体优先）。

### FastAPI 内置的就 3 个（不是"Python 常见异常各配一个"）
| 处理器 | 管什么 | 返回 |
|---|---|---|
| `HTTPException` | Web 业务异常（日常 raise 的） | 指定的 status_code + detail |
| `RequestValidationError` | 请求参数校验失败 | 422 |
| `Exception` 兜底 | 其他一切没专门处理的 | 一律 500 |

### 核心认知
- 异常处理器的职责 = **把异常翻译成 HTTP 响应**。客户端永远看不到异常，只看到 HTTP 响应。
- 日常 `raise HTTPException(409)` 也在走这套机制——只是用的是内置处理器。
- 完整旅程：`raise` → 异常冒泡 → FastAPI 查处理器 → 翻译成 JSONResponse → 过中间件 → uvicorn 序列化成 HTTP 报文 → 客户端收到。

### 分层原则（预期 vs 非预期）
| 类型 | 例子 | 怎么处理 |
|---|---|---|
| 预期异常 | IntegrityError（唯一约束冲突） | `try/except` 转特定状态码（409） |
| 非预期异常 | AttributeError、DB 断连 | **别写 `except Exception` 吞掉**，让它冒泡（FastAPI 自动 500 + traceback 进日志） |

- 想要"友好 500" → 用**全局** `@app.exception_handler(Exception)`，不要在接口里逐处写：
```python
@app.exception_handler(Exception)
async def unhandled(request, exc):
    logger.error("未处理异常", exc_info=exc)   # traceback 记全
    return JSONResponse(status_code=500, content={"detail": "服务器开小差了"})
```

---

## 三、竞态窗口：处理的三层

- **窗口无法消除，只能管理**（SELECT 和 UPDATE 之间永远有间隙）。
- **唯一约束**（`unique=True`）＝ 防脏数据的根子，不可替代。
- **捕获 `IntegrityError` → 409** ＝ 让兜底体面（必须有）。
- **软查重** ＝ 纯体验（可留可砍，web 多用户版值得留，桌面单机可砍）。
- **脏数据的代价链**：`scalar_one_or_none()` 遇到多行抛 `MultipleResultsFound` → 登录直接崩。
- **查重必须排除自己**（`id != exclude_user_id`），否则用户改回原名会被误判重复。

---

## 四、Pydantic 校验与 alias

### 挡 null / 空串
- 想要 null 失败 → **类型别写 `str | None`**（保留 `default=None` 让"缺省"合法）
- `min_length=1` 挡 `""`；`pattern=r"\S+"` 挡纯空格
- "没传"（`exclude_unset` 剔除）≠ "传 null"（校验失败）
- 字段语义分严宽：登录标识字段（如 user_name）严格；偏好字段可用 `str|None` 支持"传 null 清空"

### alias
- `alias` = **输入侧**翻译（前端传 `username` → 填进内部 `user_name`）
- `serialization_alias` = 输出侧；`by_alias=True` = 输出时用别名
- `model_dump(exclude_unset=True)` 默认输出**字段名**（非 alias）→ 天然对齐列名
- 效果：对外契约统一 `username`/`hobby`，内部统一 `user_name`/`personal_preference`，零手动映射

---

## 五、顺手收获

- **FastAPI 自动序列化**：正常接口直接 `return dict`，别 `json.dumps()`（会双重转义、datetime 崩）；只有 SSE 流式才手动拼 JSON 字符串。
- **日志**：`logger.exception(e)` 是把 e 当 message（丢堆栈）；正确是 `logger.error("文案", exc_info=exc)`。
- **分层**：repository 只做持久化、不抛 `HTTPException`（不依赖表现层）；异常→HTTP 的转换在 service 层。
- **ID 类型**：uuid.UUID 是原生形态，JWT/Redis/API 边界转 str，回 DB 查询转回 uuid.UUID。
- **查重时机优化**：只在 `update_dict` 含 `user_name` 时才查重，省一次无用查询。

---

## 一句话复盘

这个接口从"必崩"到"能通"，其实就是把最基本的工程纪律一条条落实：
**每个 async 调用都 await、参数对位、别把语句对象当实例、字段名对齐、预期异常转码、非预期异常别吞**。
没有高深的东西，全是基本功，但每一条都真的会崩。

---
---

# 【第二部分】coder 子代理重构 + HITL（2026-09-14）

> 主题：手搓 ReAct 循环跑通 + HITL 中断方案定型 + 踩坑合集
> 状态：**M1 跑通**（读/写/错误恢复三组实测）；`review_node` 写了一半；主管图仍是 stub

## 〇、进度快照

| 模块 | 状态 | 说明 |
|---|---|---|
| `node/coder.py` ReAct 循环 | ✅ 跑通 | `prepare → model → tools → model` 闭环，无 workaround |
| `node/coder_tools.py` | ✅ | 同步 `_run`，**尚无 `interrupt()`** |
| `state.py` `CoderState` | ✅ | `subagent_task: str`（必填）+ `coder_messages` |
| `prompt/coder.txt` | ⚠️ 占位版 | 9 行，**不是定稿** |
| `core/agent_graph.py` PG saver | ✅ 已有 | `AsyncPostgresSaver` + `AsyncConnectionPool`，已挂 lifespan |
| `agent/graph.py` 主管图 | ❌ **stub** | `build_graph` 未实现 —— **当前链路唯一断点** |
| `review_node` | 🚧 半成品 | 见 §五 |
| L2 中断冒泡 | ❌ 未验 | |

🔴 **关键认知纠正**：PG checkpointer **早就有**，放在最外层（`build_graph(saver)`）——**位置本来就是对
的**。子图 `coder_graph` 裸编译、不带 saver，也是对的。别把"子图没 saver"误读成"项目没 saver"。

## 一、实测记录（3 组，全过）

| 场景 | 消息流 | 结论 |
|---|---|---|
| 单轮读取 | Human → AI(read_file) → Tool → AI | 4 条，闭环 |
| **多轮 read→write** | Human → AI(read) → Tool → AI(write) → Tool → AI | **6 条，证明循环真的闭合** |
| 错误路径（文件不存在） | … → Tool(Errno 2) → AI("任务无法完成…") | 工具报错不崩图，模型正确汇报失败 |

**提示词效果对比**（同一写入任务）：

| | 无 prompt | 有 prompt |
|---|---|---|
| 消息数 | 8 | **4** |
| 白烧往返 | 1 次（路径猜成 `sandbox/memo.txt`） | 0 |
| 绝对路径泄漏 | 有 | 无 |

## 二、踩过的坑（本阶段）

| # | 坑 | 现象 | 教训 |
|---|---|---|---|
| 1 | 节点签名带多余必填参数 `model_node(state, tools)` | **compile 静默通过**，运行期 `TypeError: missing 1 required positional argument` | **LangGraph 节点只能收 `state`**（和名为 `config` 的参数）。绑工具用模块级或闭包。**反复踩了 4 次** |
| 2 | `add_conditional_edges(model_node, ...)` 传函数对象 | build 期不报错，compile 期 `ValueError: Found edge starting at unknown node '<function ...>'` | 第一个参数是**节点名字符串** |
| 3 | `add_edge("tool_node", ...)` | `ValueError: Found edge starting at unknown node 'tool_node'` | 把**映射表 key** 当成了**节点名**（差一个 `s`） |
| 4 | 缺 `add_edge(START, ...)` | `ValueError: Graph must have an entrypoint` | 必须显式声明入口 |
| 5 | `state.getattr(state, "x", d)` | `AttributeError: 'ChildState' object has no attribute 'getattr'` | `getattr` 是**内置函数**，不是方法 |
| 6 | `message.get(AIMessage.tool_calls)` | `hasattr(m,'get')` = `False`；类级访问字段也 AttributeError | `AIMessage` 是 **Pydantic 模型不是 dict**；`.tool_calls` 必须**实例属性访问** |
| 7 | `latest["tool_calls"]` | TypeError | 同 #6，**同一个病根** |
| 8 | `c not in white_list`（`c` 是 dict，列表装的是 str） | **不报错**，永远为 `True` → 所有工具都被判成高危 | ⚠️ **静默错误，最危险的一类** |
| 9 | `ToolNode.ainvoke(list)` 后取 `r["messages"]` | `TypeError: list indices must be integers` | ToolNode **输入输出配对**：传 list 返 list，传 dict 返 dict |
| 10 | prompt 路径写死 `C:/furina-agent/...` | 分发到 Linux 第一行就炸 | 硬编码绝对路径 |
| 11 | `return {"": ""}` 空 key | 占位没填就跑了 | |

**病根归纳**：`#2 #3 #6 #7` 是同一类 —— **搞混了"对象"和"标识符"**（函数对象 vs 节点名、映射 key vs 节点名、
类级 vs 实例级、dict vs 模型）。读报错时先问：**它说的那个名字在哪一侧？**

## 三、知识点

### A. 图的装配

- **节点签名**：只能 `state`（+ 可选 `config`）。多一个必填参数 = 运行期炸，编译期不报。
- **条件边机制**：函数返回**字符串** → 拿它去查映射表的 key → 跳到对应节点。查不到就报错。
- **两个命名空间，别混**：

  | | 取值 | 谁在用 |
  |---|---|---|
  | 节点名 | `prepare_node` / `model_node` / `tools_node` | `add_node`、`add_edge`、映射表的 **value** |
  | 路由 key | `tools_node` / `END` | 映射表的 **key**，即条件边函数的返回值 |

- **`Command(goto=..., update=...)`**：节点自己完成"路由 + 改 state"。返回 `Command` 的节点**后面不挂条件边**。
  `goto` 用**节点名**，`update` 格式和普通节点 return 一样。
- **编译期才做的检查**：entrypoint 缺失、edge 起点不存在 —— 都是 `compile()` 才报，`add_*` 阶段静默。

### B. State 与消息

- **可见性由 schema 决定**：挂子图时，子图只看得见**自己声明过**的字段；父图独有的字段子图拿不到（**静默**，无警告）。这不是坑，是 `add_node` 的设计前提。
- **官方两种模式**：`add_node` 用于"父子**共享** key"；要私有消息历史用"**节点内 invoke 子图** + 显式转换"。
- **`add_messages` 是追加语义**（不是替换）。且会把**裸字符串 coerce 成 `HumanMessage`** —— 所以往消息流里塞错误字符串，模型会把它当成用户说的话。
- **`AIMessage.tool_calls`**：`list[ToolCall]`，`default_factory=list`，**永远是 `[]` 不是 `None`**（构造传 `None` 会 ValidationError）。
- ⚠️ **`invalid_tool_calls` 静默洞**：模型给的参数不是合法 JSON 时，调用落到 **`invalid_tool_calls`**，而 `tool_calls` 变成 `[]`
  → 条件边判成"结束" → **图正常结束，工具没执行**。ToolNode 也不处理这个字段。

### C. ToolNode

- **它是执行器**，不是容器。源码 `tool_node.py:1105` → `await tool.ainvoke(call_args, config)`，**真的调用工具**。
- **默认只兜 `ToolInvocationError`**（`_default_handle_tool_errors` 会 re-raise 其他异常）→ 要"工具异常绝不崩图"，必须 `handle_tool_errors=True`。
- ✅ **中断会冒泡**：源码 `except GraphBubbleUp: raise`，注释点名场景 `a GraphInterrupt is raised inside a tool` 和
  `supervisor w/ tools multi-agent architecture`。
- `messages_key="coder_messages"` 用于适配自定义字段名。
- **输入输出配对**：list→list，dict→dict。

### D. HITL / interrupt

- **`interrupt()` 挂在节点函数体内**。不是条件边（它不是节点，不落 checkpoint）、不是装配代码、不是中间件。
- **三条硬性前提**：① 在节点内 ② **最外层**图 `compile(checkpointer=...)` ③ config 有 `thread_id`。
- 🔴 **checkpointer 只挂最外层，子图不带**（官方规则："compile only the outermost graph with a checkpointer, leave subagents without their own checkpointer"）。
  给子图加 saver → 中断被子图自己接住 → 主管永远看不见。
- **resume = 节点级重跑**：`interrupt()` **之前**的代码会再执行一遍 → 必须**幂等**（只能读，不能写）。
- `Command(resume=...)` 是**唯一**能作为 `invoke()` 输入的 Command；`Command(update=/goto=)` 只能在节点里 return。
- 中断载荷：`invoke` 在 `result["__interrupt__"]`；v3 event streaming 在 `stream.interrupts`。
- ⚠️ **载荷必须 JSON 可序列化** → Pydantic 模型要 `.model_dump()`。
- ⚠️ **每个 `tool_call` 必须恰好配一条 `ToolMessage`**，成功失败都要有。否则回模型时后端 400
  （`messages with role 'tool' must be a response to a preceding message with 'tool_calls'`）。

### E. 官方方案现状（2026-09 核实）

- **官方推荐 subagents as tools**：`@tool` 包 `subagent.invoke(...)`，**不是**把子代理当 graph node。
- `langgraph-supervisor`（workers as graph nodes 方案）**已停维护**，官方给了迁移指南。
- 官方 middleware 的 HITL 载荷是 `{name, args, description: str}` —— **装不下结构化 diff**。
- 官方也明说：子代理需要"clarification or **approval** before proceeding"时，就在子代理里用 `interrupt()`。

## 四、被推翻 / 修正的旧结论

| 旧结论（出处） | 现状 |
|---|---|
| §14.2 ②「结构化 `{path,diff,old_hash}` **只有**工具内 `interrupt()` 能给」 | ❌ **错**。独立审批节点的 `interrupt()` 载荷**同样是任意 dict**。当时被 middleware 的 `description: str` 限制住了，误推到"只能塞工具里" |
| §14.1 HITL 方案 = `interrupt()` 内嵌进自写 `BaseTool` | ⚠️ **改为独立 `review_node`**。三条理由：① 工具保持纯净（自动场景可复用）② 多个 tool_calls 一次审批 ③ **拒绝后能 `Command(goto="model_node")` 真的打回**，工具内只能返回字符串假装失败 |
| §14.4「A 路线中断冒泡**待验证**」 | ✅ **已证**：ToolNode `except GraphBubbleUp: raise`，注释点名 supervisor w/ tools 场景 |
| 9.14 §二「父图声明、子图没声明的 key 子图看不见」 | ✅ 成立。但这是 `add_node` 的**适用前提**（父子共享 key），是特性不是坑。**A-6 实验可以取消** |
| 9.14 坑 1「resume 是节点级重跑」 | ✅ 官方文档原文证实，**不用再验** |

## 五、待办

> ### ✅ 9-15 收工 —— 中断冒泡验证通过（9-14 的 A-2 实验）
>
> **成果（实测，非推断）**：
> - `build_graph` 改走 **B 方案**（内部 `compile(checkpointer=saver)`）→ 返回 `CompiledStateGraph`
> - **端到端实测**：真 LLM → `write_file_tool` → `review_node` → **中断冒泡到主管图** ✅
>
>   ```
>   RESULT keys : ['messages','mode','subagent_task','__interrupt__']
>   INTERRUPT   : [Interrupt(value={'type':'review_request', 'requests':[{...}]}, id=...)]
>   SNAPSHOT next: ('coder_graph',)     ← 停在可 resume 的位置
>   ```
> - 载荷 JSON 可序列化 ✅ ｜ 子图私有字段 `coder_messages` **未泄漏**到父图 state ✅
>
> **遗留**：
> - 🔴 `coder.py:73` 的 `args["path"]` **漏改**（`agent_dependencies.py:58/75` 已改成 `file_path`）
>   —— 差这一行，上面那段结果才跑得出来
> - `backend/app/agent/node/coder.py~` 是 Vim 备份文件，别提交
>
> **今天的教训**：
>
> 1. 改完 `agent_dependencies.py` 却没跑一次 → `coder.py` 的漏改藏了一下午。**铁律：改一处，跑一次。**
> 2. **20:35 误触 `git revert 6b8c35b`** → 差点抹掉全天成果（删了 `agent_dependencies.py`，
>    回退了 `coder.py` / `model.py` / `pyproject.toml` / `uv.lock`）。
>    **没丢的原因只有一个：`6b8c35b` 已经 push 了。**
>
>    🔑 **`git revert` ≠ 撤销**。它是「**反做**某个提交 + **产生一个新提交**」，历史照样保留，
>    用于撤销**已经 push 出去**的提交。要撤销**还没 push** 的本地提交，用的是 `git reset`。
>    **在 IDE 的 Git 面板里点任何按钮前，先在终端 `git log --oneline -5` 看一眼。**
>
>    🆘 **救命命令：`git reflog`** —— 记录 HEAD 的每一次移动，能找回几乎所有"丢了"的东西。
>    今天那个被丢弃的 revert 提交，现在依然躺在 reflog 里，一条 `git reset --hard 924212f` 就能回去。

---

> ### 🎯 明日开工（2026-09-16）—— 主题：**人机协作闭环**
>
> **为什么是这件事**：中断只做了一半，**一半的中断没有用** —— 它的全部价值在"人介入后流程继续"。
> 而且 resume 是面试必问题（"你的 Agent 中断后怎么恢复？"）。
>
> **步骤（按序，每步有可验产出）**：
>
> - [x] 1. ~~补 `coder.py:73` → `args["file_path"]`~~ ✅ **已完成**（含在 `6b8c35b` 里）
> - [ ] 2. `review_node` 接上 `agent_dependencies.build_write_review`，把手搓的假数据
>          （`is_new_file=True, old_hash="str"`）换成**真 diff**（30 分钟）
> - [ ] 3. `review_node` 实现路由：`return Command(goto=...)`（60 分钟）
> - [ ] 4. 条件边从 `review_node` 后**挪到** `model_node` 后（15 分钟）
>          —— 否则模型纯文本回复时也会中断（构造空载荷）
> - [ ] 5. **跑通「中断 → `resume(全批准)` → 工具真的执行」** ← 明天的验收
> - [ ] 6. **跑通「中断 → `resume(全拒绝)` → 打回 `model_node`」**
>
> **明天明确不做**：
> - ❌ **部分批准** —— `ToolNode` 无法只执行一部分 `tool_calls`，这面墙留到后面专门打
> - ❌ **主管图那 5 个业务节点** —— 下一场战役，做一半两头不靠
> - ❌ 前端 / SSE 对接
>
> **要盯住的坑**：
> - resume 是**节点级重跑** → `review_node` 里 `interrupt()` **之前**的代码必须幂等
>   （`build_write_review` 只读 ✅ 天然幂等）
> - **每一个** `tool_call` 都必须配一条 `ToolMessage`，漏一个 → 下一轮调模型时 400（离现场很远）

---
---

# 【第三部分】HITL 中断贯通 + git 事故（2026-09-15）

> 主题：契约定稿 → 图装配（B 方案）→ 中断冒泡验证 → 误触 revert 事故
> 状态：**中断已验证贯通**（真 LLM + 真实父子图）；`review_node` **尚未**接上 `build_write_review`

## 〇、进度快照

| 模块 | 状态 | 说明 |
|---|---|---|
| `schemas/model.py` 契约 | ✅ 定稿 | `ReviewAction` / `WritePreview` / `ReviewRequest` / `ItemDecision` / `ReviewDecision` |
| `agent_dependencies.py` | ✅ 写好 | ⚠️ **但没被任何地方调用** |
| `agent/graph.py` 装配 | ✅ B 方案 | 内部 `compile(checkpointer=saver)`，返回 `CompiledStateGraph` |
| **中断冒泡** | ✅ **已实测** | 真 LLM + 父子图，`__interrupt__` 正常出现 |
| `review_node` | 🚧 半成品 | 能中断，但用的是**硬编码假载荷**，且无 `return` |
| resume（恢复） | ❌ 未做 | 中断的另一半 |
| 主管图 5 节点 | ❌ 全 stub | |

## 一、今天的实测成果

**中断冒泡（9-14 的 A-2 实验，通过）**：

```
RESULT keys : ['messages', 'mode', 'subagent_task', '__interrupt__']
INTERRUPT   : [Interrupt(value={'type': 'review_request', 'action': 'review_request',
                'requests': [{'tool_call_id': 'call_00_PBvliIzPYRccUiO6cPH01276',
                              'path': 'memo.txt', 'is_new_file': True,
                              'old_hash': None, 'added': 0, 'removed': 0, 'diff': ''}]},
                id='3640e45ab74e10753a6ea95022e48b89')]
SNAPSHOT next: ('coder_graph',)
```

**一次验证四件事**：

| 验证项 | 结果 |
|---|---|
| 子图内 `interrupt()` 能否冒泡到父图 | ✅ 能 |
| 载荷能否 JSON 序列化 | ✅ 纯 dict（`StrEnum` 也没出问题） |
| 图是否停在可 resume 的位置 | ✅ `next: ('coder_graph',)` |
| 子图私有字段是否隔离 | ✅ 父图 state 里**没有** `coder_messages` |

> 最后一条证明 9-14 §二 那个"父图声明、子图没声明的 key 看不见"的假设**成立**，整套 State 设计的地基是稳的。

---

## 二、`agent_dependencies.py` 精读 ⭐

> 这文件是我"边问 AI 边理解思路抄的"，所以要分清：**哪些是抄对了的承重墙，哪些是我没看出来的雷。**

### 2.1 六处"抄得值"的设计（都是真功夫）

| # | 代码 | 为什么值钱 |
|---|---|---|
| 1 | `def f(*, sandbox_root, rel_path)` | **用签名防呆**。两个参数都是路径，位置传参极易搞反，`*` 强制关键字。类型系统防不住的，用签名防 |
| 2 | `target.is_relative_to(root)` | **不能用字符串 `startswith`**！`"/sandbox-evil".startswith("/sandbox")` → `True`（错误放行）；`is_relative_to` → `False` ✅ |
| 3 | `(root / rel_path).resolve()` | **`.resolve()` 顺带干掉 symlink 攻击**：沙箱里 `link -> /etc/passwd`，解析后是真实路径，被下一行的 `is_relative_to` 挡住 |
| 4 | `.replace("\r\n","\n").replace("\r","\n")` | **顺序不能反**！先换 `\r` 的话，`\r\n` 会变成 `\n\n`（凭空多一个空行） |
| 5 | `splitlines(keepends=True)` | 不加 `keepends`，行尾 `\n` 被剥掉 → `unified_diff` 输出**全部粘连成一行** |
| 6 | 计数时排除 `+++` / `---` | 不排除的话，diff 头 `+++ b/x` 会被算成 1 行新增，**每个 diff 都白多算一行** |

### 2.2 承重墙：**纵深防御**（这段最值得反复看）

```python
if candidate_input.is_absolute():          # ← 第一道门：挡不全
    raise ValueError(...)
target = (root / rel_path).resolve()
if not target.is_relative_to(root):        # ← 第二道门：真正兜住的那个
    raise ValueError(...)
```

**为什么第一道门挡不全？**

Windows 上 `PureWindowsPath("/etc/passwd").is_absolute()` → **`False`**（没有盘符，只有 root）。
但 `root / "/etc/passwd"` 会**替换**掉左边的 root → `/etc/passwd`。

**所以 `is_absolute()` 放行了"根相对路径"。**

**是第二道门 `is_relative_to` 接住的。**

→ 🎓 **教训：安全检查不能只有一个点。** 第一道门是"意图检查"，第二道门是"结果校验"。
**结果校验才是不可绕过的那个** —— 因为它比对的是 `.resolve()` 之后的**真实路径**。

### 2.3 两个真 bug

**🔴 bug 1 · 第 11 行 `and` 应该是 `or`**

```python
if not rel_path and rel_path.strip() == "":
```

| 输入 | 结果 |
|---|---|
| `""` | ✅ 抛错 |
| `"   "`（纯空格） | ❌ `not "   "` = False → **短路漏过** |
| `None` | ❌ `None.strip()` → **AttributeError** |

改成 `if not rel_path or not rel_path.strip():`

> 这又是一次**静默型** —— 和你 `NOTES §1` 记的 `c not in white_list` 同一个病根：**布尔逻辑写反，不报错。**

**🔴 bug 2 · diff 里泄漏绝对路径（第三次了）**

```python
add, remove, diff = make_diff(old_content, new_content, str(target))   # ← str(target) = 绝对路径
...
return WritePreview(
    path = tool_call["args"]["file_path"],    # ← 相对路径
    diff = diff,                              # ← 但 diff 头里是绝对路径！
)
```

**同一个函数，两个字段用了不同的路径基准。** 产出会长这样：

```
--- a/C:\furina-agent\sandbox\memo.txt
+++ b/C:\furina-agent\sandbox\memo.txt
```

**契约白纸黑字写着"沙箱相对，不给绝对路径"** —— 而这是**第三次**出现绝对路径泄漏（前两次见 §二 的账）。

**修法**：把 `str(target)` 换成 `rel_path`。

### 2.4 一个没处理的边界

```python
if target.is_file():     # ← 路径存在但是个【目录】时，返回 False
```

目录会被**误判成"新文件"**，一路走到审批通过、然后写入时报 `IsADirectoryError`。

**用户批了一个注定失败的操作** —— 这正是那天讨论"审批节点该做路径预检"的场景。

---

## 三、今天踩的坑（全表）

| # | 坑 | 现象 | 教训 |
|---|---|---|---|
| 1 | `args["path"]` vs 工具 schema 的 `file_path` | `KeyError: 'path'` | **同一个问题出现在两个文件，只改了一处** |
| 2 | `build_graph` 返回未编译的 builder | `has ainvoke: False`，且 `saver` 参数**从未被使用** | **签名/实现/调用方三方必须对齐** |
| 3 | `interrupt({payload})` 把 Pydantic 对象塞进 set | `TypeError: unhashable` | 抛出去的是 **JSON dict**，不是对象 |
| 4 | 给 `added/removed/diff` 加默认值 | `is_new_file=True, old_hash="str"` 这种**假载荷也能过校验** | **默认值不能和真实语义撞车**（`added=0` 本身就是"没改动"的合法含义） |
| 5 | `diff: str = None` | 注解说 `str`，实际是 `None` | 类型谎言，应写 `str \| None` |
| 6 | 条件边挂在 `review_node` 后 | 模型**纯文本回复时也会中断**（构造空载荷） | 有 `tool_calls` 才该进 review |
| 7 | 误触 `git revert` | 5 个文件被删/回退 | **`revert` ≠ 撤销**（见 §五） |

---

## 四、知识点沉淀

### A. LangGraph 子图与中断

- **中断冒泡三前提**：① 在节点内 ② **最外层**图 `compile(checkpointer=...)` ③ config 有 `thread_id`
- **子图挂 `add_node`**：子图**只看得见两边都声明过的字段**；共享靠**名字逐字一致**，不靠类型
- **`next: ('coder_graph',)`** —— 图停在**子图节点**上，resume 从那里继续
- **顶层 state 的 schema 决定子图输出什么**：`coder_messages` 父图没声明 → 被丢弃（这就是"子图私有消息"的实现原理）
- **resume 是节点级重跑** → `interrupt()` **之前**的代码必须**幂等**

### B. 路径安全（今天最大的认知升级）

| 手段 | 挡什么 | 挡不住什么 |
|---|---|---|
| `is_absolute()` | 带盘符的绝对路径 | **根相对路径**（`/etc/passwd` 在 Windows 上是 `False`） |
| `.resolve()` | symlink 指向的真实路径 | —— |
| `is_relative_to()` | **一切逃逸**（比对真实路径） | ——（前提：`root` 也 resolve 过） |
| `startswith()` | ❌ **不要用** | `/sandbox-evil` 会被 `/sandbox` 前缀放行 |

### C. Pydantic / StrEnum

- **Pydantic 是运行时校验器** —— `Literal` 写在 Pydantic 字段里，**传错值当场 `ValidationError`**（不是"只给 IDE 看"）
- `model_dump()` → 枚举成员**对象**；`model_dump(mode="json")` → 纯字符串
- `StrEnum` 继承 `str` → 即使 dump 成成员，`json.dumps` 也**兜得住**（普通 `Enum` 会 `TypeError`）
- `model_validate()` 把 dict 还原成模型 —— interrupt 收回侧要用

### D. git

- **`revert` ≠ 撤销**：它是"反做 + 产生新提交"，历史保留
- **`reset`** 才是"丢掉本地未 push 的提交"
- **`reflog` 是后悔药**

---

## 五、git 事故复盘（2026-09-15 20:35）

**发生了什么**：误触 `git revert 6b8c35b` → 生成 `924212f`，删掉 `agent_dependencies.py`，回退
`coder.py` / `model.py` / `pyproject.toml` / `uv.lock`。

**为什么毫发无伤**：**`6b8c35b` 已经 push 了**。远程有完整副本。

**修复**：
```bash
git restore --source=6b8c35b -- <5个文件>   # 恢复文件
git reset 6b8c35b                            # 丢弃误操作的提交（--mixed，保留工作区）
```

**两条护栏**：
1. **提交完立刻 `push`** —— 今天的保险费，别省
2. **在 IDE 里点 Git 按钮前，先在终端 `git log --oneline -5` 看一眼**（IDE 对危险操作的提示太弱）

**救命命令**：`git reflog -10` —— HEAD 的每一次移动都有记录，**git 几乎不会真的丢东西**。

---

### 📦 9-14 的旧计划（已完成，留档）

> ### 🎯 明日开工（2026-09-15）—— 只做这两件
>
> 1. **设计 interrupt 载荷**
>    - `ReviewRequest`：中断抛出（`action` 判别字段 + `requests: list[WritePreview]`）
>    - `ReviewDecision`：resume 收回（`action: Literal["approve","reject"]` + 可选 `reason`）
>    - ⚠️ Pydantic 模型不是 JSON 可序列化 → 抛/收都走 `.model_dump()` / `.model_validate()`
>    - `WritePreview` 字段参考：`tool_call_id` / `path`（沙箱相对，**不给绝对路径**）/ `is_new_file` / `old_hash` / `added` / `removed` / `diff`
> 2. **初步实现 HITL**
>    - 修 `review_node` 现有 bug → `Command(goto="tools_node" | "model_node")` 路由
>    - `should_continue` 有 tool_calls 时改指向 `"review_node"`
>    - ⚠️ 拒绝分支必须给**每一个** tool_call 补 `ToolMessage`（不只是被拒的那个）

**🔴 当前断点**：`agent/graph.py` 的 `build_graph` 还是 stub。`agent_graph.py:28` 已经在调 `build_graph(saver)`，
但里面没挂任何节点。**在这之前，`review_node` 里的 `interrupt()` 跑起来只会静默不中断。**

**`review_node` 现有 3 个 bug**（写了一半）：

```python
latest["tool_calls"]              # ❌ AIMessage 是对象不是 dict → TypeError
risky_tools not in white_list     # ❌ dict 永不在 str 列表里 → 永远 True（静默）
withe_list                        # ⚠️ 已改名 white_list ✅
```

**顺序**：

- [ ] 1. `graph.py` 补最小 `build_graph`：`START → coder 子图 → END`，`compile(checkpointer=saver)`
- [ ] 2. `review_node` 修完 + `Command(goto=...)` 路由 + `should_continue` 改指向 `review_node`
- [ ] 3. 载荷定稿：`ReviewRequest`（中断抛出）/ `ReviewDecision`（resume 收回），走 `.model_dump()` / `model_validate()`
- [ ] 4. `WriteFileTool` 加 diff 计算（幂等！）
- [ ] 5. 跑通"批准 → 执行"和"拒绝 → 打回 model"两条路
- [ ] 6. 再接主管图那 5 个业务节点

**该记的账（不影响验收，攒着一起还）**：

- prompt 路径硬编码绝对路径 → 分发必炸
- `model_node` 每次调用读一遍 prompt 文件
- 绝对路径泄漏（已观察到 2 次）
- `coder.py` 顶部 docstring 图结构过时（缺 prepare / review）
- `invalid_tool_calls` 洞未堵
- A-7 残留：挂上 checkpointer 后，第二次调用 coder 时 `coder_messages` 会累积

---
---

# 【第四部分】review_node 定稿 + 用测试脚手架代替"干想"（2026-09-16）

> 主题：HITL 审批闭环的核心逻辑跑通 ｜ 踩坑 → 换数据结构 → 上测试
> 状态：**核心逻辑实测通过**（9 个 case，主路径全绿）；`rollback_tool_messages` 抽出但**尚未接线**

## 〇、进度快照

| 模块 | 状态 | 说明 |
|---|---|---|
| `review_node` 核心逻辑 | ✅ **实测通过** | case3（混合调用·拒中间）三条消息全对、顺序正确 |
| 图装配 | ✅ | 条件边挪到 `model_node` 后；`review_node` 无出边，全交 `Command(goto=)` |
| `build_tool_messages` | ✅ | **今天长出来的唯一一个新抽象**：统一的"回执"构造器 |
| `_t_review.py` 测试脚手架 | ✅ | monkeypatch `interrupt`，绕开真图直接调节点；9 case 秒级反馈 |
| `rollback_tool_messages` | 🚧 | 抽出来了，但只有 `pass` —— `review_node` 还在用内联版 |
| unknown 工具名 | 🔴 **实测抓到会崩** | 见 §七 |
| 接真图端到端 | ❌ 未做 | 批准 → 沙箱真有文件；拒绝 → 真没有 |

## 一、今天的验收：case 3 是分水岭

一轮调 `read_file_tool` + `write_file_tool` + `write_file_tool`，**只拒中间那个**：

```
[3 混合-拒中间]  goto=model_node   msgs=3
      A 同批次有操作被拒绝，本次未执行      ← 白名单工具，没执行
      B 同批次有操作被拒绝，本次未执行      ← 用户批准了，但整批回滚
      C 用户拒绝，不该动                    ← 被拒
      顺序 OK
```

**这三条各自的含义**：

| 消息 | 为什么它必须存在 |
|---|---|
| A（白名单） | 它**没执行** —— 因为你去的是 `model_node` 不是 `tools_node` |
| B（已批准） | 同上，**批准 ≠ 执行** |
| C（被拒） | 唯一带原因的 |

**漏掉任何一条 → 下一轮调模型 400。**

## 二、`agent_dependencies.py` 逐行

### 2.1 修掉的

| 行 | 原来 | 现在 | 为什么致命 |
|---|---|---|---|
| `:12` | `not rel_path **and** rel_path.strip()==""` | `**or**` ✅ | `"   "`（纯空格）漏过；`None` 直接 `AttributeError`。**布尔写反，不报错** |

### 2.2 半修 / 未修

| 行 | 问题 | 状态 |
|---|---|---|
| `:60-63` | 加了 `try/except KeyError` 但 body 只有 `raise` | ⚠️ **等于没改**（自己标了"槽点——没有防止大模型幻觉"） |
| `:68` | `target.is_file()` 对**目录**返回 `False` → 目录被判成"新文件" | ❌ 用户会批一个注定 `IsADirectoryError` 的操作 |
| `:77` | `make_diff(..., str(target))` —— **diff 头里是绝对路径** | ❌ **第 3 次**泄漏 |
| `:58-86` | 整个函数**假设「高危 = 写工具」**（要 `file_path` + `text`） | ❌ 无代码保证 → 今天 case 8 的 `KeyError` |

🔴 **同一个函数，两个基准**：

```python
path = tool_call["args"]["file_path"]   # ← 相对路径
diff = make_diff(..., str(target))      # ← 绝对路径！写进 diff 的 --- / +++ 头
```

契约白纸黑字写着「沙箱相对，**不给**绝对路径」。

## 三、`review_node` 最终骨架

```
review_node(state) -> Command
│
├─ 不是 AIMessage / 无 tool_calls ─────────────────▶ model_node      （防御）
│
├─ risky 为空（全是白名单工具）────────────────────▶ tools_node      ★ 不中断
│
├─ 【interrupt】送审 risky ──▶ Command(resume=) 收回
│
├─ resume 不是 dict ───────────────────────────────▶ model_node + 全部回执
├─ len(decisions) != len(risky) ───────────────────▶ model_node + 全部回执
│
├─ reject 为空（全批准）───────────────────────────▶ tools_node
└─ 有拒绝 ─────────────────────────────────────────▶ model_node + 全部回执
```

**装配**：

```
model_node ──条件边{review_node, END}──▶ ...
review_node ──(无出边，全由 Command(goto=) 决定)──▶ {tools_node, model_node}
tools_node ──▶ model_node
```

⚠️ **返回 `Command` 的节点后面不能挂条件边**，二者的路由会打架。

## 四、今天的 4 个 bug（按隐蔽度排序）

### 🔴 1. `d.get("action").value` —— 必崩

```python
d.get("action").value != ReviewAction.APPROVE.value
```

`Command(resume=)` 收回来的是 **JSON 反序列化的 dict**，`d["action"]` 是**字符串** `"approve"`，
**不是 `ReviewAction` 枚举成员**。字符串没有 `.value` → `AttributeError`。

实测：
```
>>> {'action':'approve'}.get('action').value
AttributeError: 'str' object has no attribute 'value'
```

> 🎓 **认知**：`model_dump(mode="json")` 出去的是纯字符串，回来**也只有纯字符串**。
> **「出是 JSON、进也是 JSON」不能推出「类型会自动还原」。**
> 选了手工解析，就得**手工对齐类型**。这就是 `model_validate()` 值钱的地方 —— 它让 `d.action` 真的是枚举成员。

### 🔴 2. 三元表达式套错了位置 —— 最隐蔽

```python
# ❌ 三元表达式套在【列表元素】位置
msg = [ build_tool_messages(tc, ...) if tc['id'] in reject else "同批次..." for tc in raw ]
#                                ↑ ToolMessage                ↑ str
```

`msg` 里混着 `ToolMessage` 和 `str` → **`add_messages` 把裸字符串 coerce 成 `HumanMessage`**
→ 模型看到的是「**用户说**：同批次有操作被拒绝」→ 而且那两个 tool_call 没有回执 → **400**。

实测：
```
>>> add_messages([ToolMessage(...)], ["裸字符串"])
['ToolMessage', 'HumanMessage']
```

> 🎓 **认知**：三元表达式要套在**参数**位置（`content=`），不是列表元素位置。
> 这条 **§三 B 已经记过**："往消息流里塞错误字符串，模型会把它当成用户说的话。"

### 🔴 3. `isinstance(command_resume, dict)` 判断反转

```python
# 注释：「不能保证前端给我们的一定是字典」
if isinstance(command_resume, dict):     # ← 代码说的是相反的事
    return Command(... 全部标成调用失败 ..., goto="model_node")
```

正常情况（前端传的就是 dict）→ **每次审批都走这个分支** → **审批结果被完全丢弃**。

> 🎓 **认知**：**注释和代码说的是相反的事**。静态看不出来，只有实测能抓。
> 自查手法：`if` 后面接的是"异常情况"分支 → 那就该是 `if not ...`。

### 🔴 4. `reject_msg + undone_msg` 拼接乱序

```
[A, B, C]  → 筛 → [C] 和 [A, B]  → 拼 → [C, A, B]
```

两个 comprehension = **两次遍历** = 两个子序列。**拼接是首尾相接，不是按原下标插入。**

> 🎓 **认知**：`msgs[i]` 必须对应 `raw_tool_calls[i]` → 那就**只能一次遍历**。
> **这是「分桶」思维的第三次复发**：
> ① `approve_tools` / `rejection_messages` ② 裸字符串两分支 ③ `reject_msg` / `undone_msg`

**正解 —— 默认 + 例外表**：

```python
blocked = {d["tool_call_id"]: d.get("reason") or "用户拒绝批准！"
           for d in tool_list
           if d.get("action") != ReviewAction.APPROVE.value}

msg = [build_tool_messages(tc, content=f"用户拒绝，{blocked[tc['id']]}"
        if tc["id"] in blocked else "同批次有操作被拒绝，本次未执行")
        for tc in raw_tool_calls]

assert [m.tool_call_id for m in msg] == [tc["id"] for tc in raw_tool_calls]   # 顺序自证
```

## 五、四条核心认知

### 1️⃣ `ToolNode` 不看你的审批结果

> **它执行 state 里那条 `AIMessage` 的 `tool_calls`。**

所以「有拒绝」**必须回 `model_node`**，不能指望 `ToolNode` 少执行几个。

### 2️⃣ 拒绝 = **整批回滚**

只要有一个被拒，整批都不执行。所以**白名单工具**、**被你批准的高危**，**也都要有 `ToolMessage`**。

### 3️⃣ 配对靠 `tool_call_id`，不靠下标 —— 而且两边字段名不同

```
tool_call : {"id": "call_A",  "name": ..., "args": {...}}
decision  : {"tool_call_id": "call_A", "action": ..., "reason": ...}
                        ↑ 多一个前缀
```

**我卡半天的直接原因就是这个。** 光靠想发现不了，`print` 一次就看见。

### 4️⃣ 小 API 细节

| 写法 | 陷阱 |
|---|---|
| `d.get(k, 默认)` | 默认值**只在 key 缺失时**生效。前端传 `"reason": null` → 拿到 `None`，不是默认值。要写 `d.get(k) or 默认` |
| `command_resume.get("decisions") or []` | 同上，`"decisions": null` 会让 `len(None)` 崩 |

## 六、方法论：测试脚手架 ⭐

**今天最大的收获不是代码，是这套做法。**

```python
# _t_review.py —— 绕开真图，直接调节点
C.interrupt = lambda _: 假的审批结果        # monkeypatch 掉 interrupt
cmd = await C.review_node(fake_state)       # 直接调，不用 LLM 不用 PG 不用 checkpointer
```

**9 个 case、秒级反馈。** 上面 4 个 bug 里有 3 个是这个脚手架抓出来的 —— 其中 #3（`isinstance` 反转）**静态审查完全看不出来**。

> 🎓 **卡住 ≠ 逻辑难，通常是这两个**：
> ① **在一个 40 行的函数里改** → 工作记忆过载 → **抽成纯函数单独跑**
> ② **只「想」不「跑」** → 字段名不同这种事实，想一万年也想不出来，`print` 一次就看见

> ⚠️ 但那两个被 monkeypatch 掉的 `interrupt`，也意味着**它不算端到端验证**。

## 七、今天挣到的账（全部未修）

- 🔴 **unknown 工具名 → `KeyError`**（case 8 实测）。
  `build_write_review` 假设 `risky` 里全是写工具。今天成立只因白名单恰好挡住了另外两个。
  **将来往 `coder_tools` 加任何非写工具（`run_shell`/`delete_file`），忘加白名单 → 整个会话 500。**
- 🟡 绝对路径泄漏进 diff 头（**第 3 次**）
- 🟡 目录被误判成"新文件"
- 🟡 文案重复：`"用户拒绝，用户拒绝批准！"`
- 🟡 `ReviewDecision` / `WritePreview` **导入了没用**（死导入）
- 🟡 `rollback_tool_messages` 是空壳，`review_node` 还在用内联版
- 🟡 `WritePreview.old_hash` 注释写着"乐观锁"，**没有任何地方校验**
- 🟡 `_t_review.py` 里靠 `exec` 切文件绕过语法错误的 hack，待清理

## 八、被否决的方案：try/except + 自定义异常 ⭐

**原始想法**：捕获异常 → 抛自定义异常 → 外层捕获 → 打回 `model_node`。

**两条硬理由否掉它**：

**① 异常不解决 400 —— 而 400 才是真正的问题**

`raise` 出去、外层捕获、`goto model_node` 之后，消息流里躺着的是：

```
HumanMessage
AIMessage(tool_calls=[X])     ← 这个请求，永远没有回应
```

`model_node` 一调 LLM → **400**。
**要修这个 400 必须补 `ToolMessage`；而一旦补了 `ToolMessage`，异常就没有存在意义了。**
异常是控制流，消息配对是数据流，两者不在一个层面。

**② 「外层捕获」在哪里？**

LangGraph 里节点抛异常 = **整个 `ainvoke` 失败**（除非配 `retry_policy`）。
**没有「节点抛异常 → 图跳到另一个节点」这种机制。**
你要么让它冒泡 → 500；要么在 `review_node` 里 `try/except` 然后 `return Command(...)`
—— 那异常压根没抛出去，它只是个局部变量。

> 🎓 **判据**：异常留给「调用方无法处理」的事。
> 这里调用方（`review_node`）**恰恰就是该处理这件事的地方**。
> **模型幻觉出工具名不是 bug，是常态，是业务输入。**

**正解：它是第三种类别，走同一套回填**

| `tc["name"]` 在哪 | 类别 | 处理 |
|---|---|---|
| 在 `white_list` | safe | 不送审，正常执行 |
| 在 `coder_tools`，不在白名单 | risky | 送审 |
| **都不在** | **unknown** | **不送审**，直接挡下 |

**unknown 根本不需要人审批** —— 审批界面给用户看什么？没有 diff、没有可预览的东西，点"拒绝"也是无信息量的一次点击。
而且 `blocked` 只是从**一个写入点**变成**两个**（用户拒绝 / 工具不存在），**内容构造一个字都不用改**。

---

> ### 🎯 明日开工（2026-09-17）—— 主题：**把 unknown 堵上 + 接真图**
>
> **为什么是这件事**：`review_node` 的纯逻辑已经对了，但**从没在真图里跑过**。
> monkeypatch 掉的 `interrupt` 是便利，也是盲区。
>
> **步骤（按序，每步有可验产出）**：
>
> - [ ] 1. 清 `_t_review.py` 的 `exec` hack（`agent_dependencies.py:99` 已补 `pass`，能正常 import 了）
> - [ ] 2. **`risky` 分三堆**：`safe` / `risky` / `unknown`，`known_tools = {t.name for t in coder_tools}`
> - [ ] 3. **unknown 短路**：非空 → 不送审，全部回填打回 `model_node`
>        边界自查：unknown 和 risky 混在一批，**还要不要弹审批？**（整批注定回 model_node，弹了有用吗）
> - [ ] 4. `blocked` 两个写入点合一
> - [ ] 5. **接真图端到端**（今日唯一真验收）：
>        - 批准 → **去沙箱目录看文件在不在**
>        - 拒绝 → **去沙箱目录看不该写的没写**
>        - 打印 `result["__interrupt__"]`，确认它第二次 `ainvoke` 后消失
> - [ ] 6. 提交 + **立刻 push**
>
> **明天明确不做**：
> - ❌ 部分批准（需要先把 state 里那条 `AIMessage` **换掉**，是另一场战役）
> - ❌ 主管图那 5 个业务节点
> - ❌ 前端 / SSE 对接
> - ❌ `build_write_review` 那 4 笔账（绝对路径 / 目录 / 乐观锁 / 泛化）—— 攒着一起还
>
> **要盯住的坑**：
> - resume 是**节点级重跑** → `interrupt()` **之前**的代码必须幂等
>   （`build_write_review` 只读 ✅；`_t_review.py` 里的 monkeypatch 只影响测试）
> - **每一个** `tool_call` 必须恰好配一条 `ToolMessage`，漏一个 → 下一轮 400（离现场很远）

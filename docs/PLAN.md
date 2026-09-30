# furina-agent 项目规划与架构决策

> 生成日期：2026-08-29 ｜ 状态：规划稿（决策已拍板，代码未动）
> 一句话定位：**求职作品 + 开源项目**，Web / 桌面双端共用一套服务端，Rust 网关承担入口与 RAG 检索，对并发有要求。
> 产品形态：**芙宁娜（原神水神）角色扮演 + 代码助手的双模式 AI**——闲聊时保持人设，代码场景收敛人设保准确性。

---

## 一、项目定位与目标

- **性质**：求职作品（工程能力展示）+ GitHub 开源 + 自用
- **形态**：Web 版一个、桌面版一个（Tauri 壳），**共用同一后端**
- **能力**：双模式——① 芙宁娜角色扮演（闲聊/剧情）② 代码助手（问答/审查/补全，RAG 检索代码知识域，需人类审批后才改文件/跑命令）
- **并发**：有要求，靠 Rust API 网关 + 可压测佐证
- **分发**：后端 Docker Compose 一键起；桌面端 GitHub Releases 自动构建三平台安装包

---

## 二、最终目标架构

```
客户端(Web / Tauri 桌面)
   │
   ▼
Rust API 网关  (axum/hyper + tokio) —— 无状态，可水平扩展
   ├─ 限流      分布式令牌桶（基于 Redis）
   ├─ JWT 鉴权   验签 + 黑名单缓存
   ├─ 路由 / 聚合
   ├─ 可观测性   metrics / 请求日志 / 健康检查
   └─ SSE 转发   对话流式数据中转
   │
   ├────────────────────────────────┐
   ▼                                ▼
FastAPI 业务后端                 Rust RAG 服务 (有状态，加载索引)
   └─ LangGraph 状态机(对话编排)     └─ embedding + 向量/全文检索，返回 top-k
       ├─ 节点：画像注入/意图路由/RAG检索/LLM流式/持久化
       └─ 条件边：要检索? / 要追问? / 要调工具?
   │
   ▼
PostgreSQL (消息/会话)  +  Redis (热缓存/会话/限流计数)
```

**关键分层原则**：
- 网关**无状态**（可扩实例）、RAG 服务**有状态**（驻留索引）→ **两个进程，不混在一个二进制里**；共享 Rust crates，进程隔离。
- FastAPI 退为纯业务后端，网关在入口统一做限流/鉴权/观测。

### RAG 知识域（多域分区）

- **world-knowledge**：原神世界观（角色/剧情/地名）——角色扮演防幻觉
- **code-knowledge**：框架文档、API 参考、用户代码库（如 Fabric 模组）——代码助手防编 API 名，呼应 Fabric 项目"RAG 检索 + 编译器兜底"结论
- Rust 服务按 `domain` 分索引/分集合，`/search` 带 domain 参数

### RAG 链路拆分（向量/检索在 Rust，编排在业务层）

**离线入库管线**（低频）：文档 → 解析 → 切块 → embedding → 建索引(ANN+BM25) → 元数据存 PG
**在线检索链路**（高频）：query → LangGraph RAG 节点 → Rust `/search` → embedding → 向量+BM25 多路召回 → RRF 融合 →（可选 rerank）→ 上下文压缩 → 注入 prompt → LLM

**Rust RAG 服务接口（钩子）**：
- `POST /index` —— 离线入库：文档/chunk → embedding → 写索引
- `POST /search` —— 在线检索：query → 多路召回 → RRF → 返回 top-k `{text, score, meta}`
- 服务不感知 LangGraph / 会话，可独立部署与压测

**职责划分**：切块 / embedding / ANN / BM25 / RRF → Rust；检索编排、上下文压缩、prompt 组装 → 业务层；rerank → MVP 先不做。

**待拍板**：① embedding 来源（本地 Strix Halo 跑 vs 外部 API，入库与检索必须同一模型）② 向量库（内嵌 `tantivy`/`usearch` vs 独立 `qdrant`）③ rerank 取舍（建议 MVP 只做 RRF）

---

## 三、已拍板的关键决策

| # | 决策 | 理由 |
|---|---|---|
| 1 | **双端共用同一后端**（桌面=客户端壳） | 一套架构故事完整；避免双份认证/部署/测试；"后端 API + 多客户端"是标准范式 |
| 2 | **Rust 网关 = API 网关 + RAG 下沉**，两进程分离 | 网关要无状态可扩展，RAG 要有状态加载索引；职责互不拖累 |
| 3 | **桌面壳用 Tauri**（Rust） | 与网关同语言栈，求职故事统一；CI 出三平台安装包 |
| 4 | **数据层 PG 单轨，不做 SQLite** | 目标用户是开发者（会用 GitHub），装 PG/Docker 不是门槛；双轨=双倍维护+双倍 bug 面；并发架构本来就是 PG 形态 |
| 5 | **认证保留多用户形态**：双令牌 + 黑名单 + 会话管理（顶号） | Web 多用户下的合理设计，是求职卖点不是冗余；但**必须接上、能讲清、有测试** |
| 6 | **Redis 保留**：热缓存 + 会话 + 限流计数 | 服务端形态的合理设施；和熔断/降级一起作为稳定性设计讲 |
| 7 | **`user_name` = 纯登录名**；`personal_preference` 承载"AI 称呼"等偏好 | 职责分离，Pydantic 校验按字段分严宽（见 §6） |
| 8 | **对话编排用 LangGraph 状态机**（FastAPI 业务层） | 把"拼 prompt 调一次 LLM"升级为有状态的 agent 工作流（意图路由/工具/循环）；与 Rust 网关/服务分层不冲突（见 §7） |
| 9 | **复杂 RAG：向量/检索在 Rust，编排在业务层** | 性能密集部分（embedding/ANN/BM25/RRF）下沉 Rust；检索编排/压缩/组装留业务层，可独立压测（见 §2 RAG 链路） |

---

## 四、当前代码缺陷清单（治理顺序）

### 4.1 修改用户信息接口（PATCH /users/me）——必崩，优先修

| 层 | 位置 | Bug |
|---|---|---|
| router | `routers/user.py:36` | `user_update(inform, session, current_user)` **缺 await**，且实参顺序与签名 `(user, session, inform)` 不符 |
| service | `services/user.py:227` | `return user_reset(...)` **缺 await**，返回 coroutine 不是 bool |
| repository | `repositories/user.py:55` | `session.refresh(stmt)` 传的是 `Update` **语句对象**，refresh 需 ORM 实例，必抛 `InvalidRequestError` |
| 字段映射 | `services/user.py:223` | schema 字段 `username`/`hobby` ≠ 列 `user_name`/`personal_preference`，`.values(**dict)` 必报 `Entity has no property`；对照 `user_create` 的映射修 |
| 校验 | `schemas/model.py:32-34` | `username: str\|None` 允许 null/空串；`user_name` 列未设 `nullable=False`，null 会把登录名清空 |

**决策**：软查重（`get_other_user_by_name`）**已砍**（单用户无意义，唯一约束兜底）。改 Pydantic 收紧 + 可选 `IntegrityError` 捕获。

### 4.2 死代码

| 文件 | 问题 | 处置 |
|---|---|---|
| `core/redis_limiter.py` | 令牌桶限流器**全项目零引用** | 要么删，要么**挂到入口路由真正生效**（否则求职负分） |
| `models/ORM.py` | 第二套 ORM 模型（`ChatMessage`），与 `table.py` 并存，零引用 | **删除**，统一用 SQLModel |

### 4.3 其他质量项

- 三个"预留"空壳路由 `knowledge/asset/ws`：**决定去留**——要么做成真的（knowledge 会被 Rust RAG 取代），要么从简历/文档里撤掉，别挂空壳
- `repositories/user.py:58` 等 `logger.exception(e)` 用法不规范（e 被当 message，丢 traceback）→ 统一 `exc_info=e`
- 对话链路**没有把用户身份注入 prompt**（见 §6）
- 无测试、无 Docker、无压测数据（见 §7 阶段 0）
- `.gitignore` 已正确忽略 `.env`/`.venv/`/`logs/` ✅（开源入场券已达标一项）

---

## 五、ID 类型规范（全项目一致）

> **规则：id 的原生形态是 `uuid.UUID`（DB 列 / ORM 对象层）；只在三个序列化边界变字符串；回 DB 查询必须转回 `uuid.UUID`。**

| 边界 | 形态 | 证据 |
|---|---|---|
| DB 列 / ORM 对象 | `uuid.UUID` | `models/table.py:13` |
| 进 JWT payload | `str()` | `security.py:66` `{"sub": str(user_id)}` |
| JWT 解码后（sub/id/session_id） | 字符串 | `dependencies.py:63` |
| 进 Redis key | 字符串 | `redis_user.py:44` |
| 出 API JSON | 字符串 | `routers/user.py:22` |
| 回 DB 查询 | `uuid.UUID(...)` 转回 | `dependencies.py:80` |

**判断口诀**：从 DB/ORM 来=UUID 对象；从 token/Redis 来=字符串；要回 DB 查=转 `uuid.UUID(...)`；要进 JWT/Redis/JSON=转 `str(...)`。

---

## 六、功能缺口：让 AI 记住用户称呼

**现状**：`SYSTEM_PROMPT` 是静态字符串（`prompts/furina.py:4`），`stream_chat` 拼 messages 只用「system + 历史 + 当前输入」，`chat.py` 加载的 `user` 对象仅用于归属校验后被丢弃——**AI 根本看不到 `user_name`/`personal_preference`**。

**结论**：改 `user_name` 不会让 AI 记住称呼，必须先打通 prompt 注入。

**方案（三处钩子）**：
1. `prompts/furina.py`：静态常量改为 `build_system_prompt(user)` 函数，把 `user.user_name` / `user.personal_preference` 拼进去
2. `services/stream.py`：`stream_chat` 增加 `user` 参数，`messages[0]` 用 `build_system_prompt(user)`
3. `routers/chat.py`：调用时把 `user` 传入（它本来就有）

---

## 七、LangGraph 状态机（对话编排）

### 定位

FastAPI 业务后端的对话编排引擎，**取代 `services/stream.py::stream_chat` 的线性拼 prompt**。
分工：Rust 网关管"入口"（鉴权/限流/路由），LangGraph 管"业务怎么走"（编排）。

### 状态图（钩子级）

```
State: { user_profile, conversation_id, messages, retrieval_results, pending_intent }

Start ──▶ 用户画像注入 ──▶ 意图路由
   ├─(需要检索)──▶ RAG 检索节点(调 Rust RAG 服务) ──┐
   └─(直接回答)─────────────────────────────────┴──▶ LLM 生成节点(流式)
      LLM 生成 ──(需追问/调工具)──▶ 回意图路由(循环)
              └─(完成)──▶ 持久化节点(写 Message) ──▶ END
```

### 节点职责

- **用户画像注入**：把 `user_name` / `personal_preference` 写进上下文（顺带解决 §6 缺口）
- **人设注入（按 mode 切换）**：`state.mode` = `roleplay` / `code` → 闲聊注入全人设，代码场景注入"收敛人设"（保说话风格、准确性优先）
- **意图路由**：条件边判断"要不要检索 / 要不要调工具 / 闲聊还是代码"（规则优先，LLM 兜底，默认闲聊）
- **RAG 检索**：HTTP/gRPC 调 Rust RAG 服务（带 domain 参数，区分原神/代码知识域），结果注入 state
- **LLM 生成**：流式输出（`astream_events`），对接现有 SSE
- **工具节点 + human-in-the-loop**：改文件/跑命令必须 `interrupt()` 等用户审批后再继续（LangGraph 原生支持，安全边界是面试加分项）
- **持久化**：写回 Conversation / Message（复用现有表）

### 与现有代码的关系

- `stream_chat` 被 StateGraph 取代；`repositories/message.py` 消息存取保留
- checkpointer 可把图状态存 PG/Redis，复用现有会话体系

### 引入理由（不是玩具的又一证据）

- 有状态 + 条件路由 + 循环，比单次 prompt 调用高一个档次
- 给工具调用（出图 / TTS / RAG）和未来多智能体留了正门
- 与 Rust 网关/服务清晰分层：网关管入口，LangGraph 管编排

### 待确认决策

- 状态机要编排哪些动作（仅 RAG？还是含出图 / TTS 工具）→ 定工具清单
- checkpointer 持久化到 PG 还是 Redis

---

## 八、落地路线（分期）

| 阶段 | 内容 | 产出 |
|---|---|---|
| **0 治理** | 删 `ORM.py`；限流器接上或删除；修 PATCH /users/me 全部 bug；Pydantic 收紧；补 `pytest`（认证+会话+update）；Docker Compose（PG+Redis+FastAPI）；`config.py` API_KEY 必填改可选；README 骨架 | 无玩具感、可复现 |
| **1 网关** | Rust 网关最小可用：JWT 鉴权 + 限流 + 路由 + SSE 转发；FastAPI 退业务后端 | 单入口 |
| **2 RAG** | Rust RAG 服务：embedding + 向量检索闭环；替换 knowledge 空壳；确认 embedding 生成方式（外部 API / 本地 Strix Halo 跑） | 真知识库 |
| **3 桌面** | Tauri 桌面壳，共用同一 API；GitHub Actions 出三平台安装包 | 双端齐 |
| **4 佐证** | k6/wrk 压测报告；metrics 面板；README 架构图 + 截图 + 压测数字；补 LICENSE | "并发"有数字 |

---

## 九、开源分发策略

- **后端**：Docker Compose 一键起（PG+Redis+FastAPI 都在编排里）；`.env.example` 全字段注释
- **桌面端**：GitHub Actions 按 tag 构建 `.msi/.dmg/.deb+appimage` 推 Releases，内置 auto-update
- **LLM key**：抽象成 OpenAI 兼容（`base_url`+`key`，DeepSeek 天然兼容）；**提供本地 Ollama/LM Studio 兜底**，让无 key 用户也能跑
- **配套**：`LICENSE`（MIT 或 Apache-2.0，别用 AGPL）、README（架构图+快速开始+截图+压测）、CI 绿标、Issue 模板
- **你的 Y7000 角色转变**：从"分发依赖"变成"自己的生产部署 + 压测环境 + CI 验证目标"

**两个必须先填的工程坑（文档救不了）**：
1. `config.py` API_KEY 必填 `raise` → 开源版要允许空 key（启动给清晰错误）或本地模型兜底
2. 别人没有建好的库 → Compose 用 `POSTGRES_DB` 自动建，或给 `psql` 建库 SQL（`create_table` 已能自动建表）

---

## 十、安装文档规范（五板块）

1. **前置要求**（第一屏）：Docker 或自装 PG16+Redis；两条路写清
2. **配置**：`.env.example` 逐字段注释（必填/可默认）
3. **启动**：Compose 一条龙 / 无 Docker 路径（建库 SQL + uv/cargo 命令）
4. **验证**：冒烟命令（`curl /`、注册登录）
5. **FAQ**：端口冲突、表没建、镜像加速、连接被拒、uv/cargo 换源（复用自己踩坑经验）

**合格线**：照抄能通、配置有示例、装完能验证。

---

## 十一、待办追踪（下次开工从这挑）

- [ ] 修 PATCH /users/me 四个 bug（§4.1）
- [ ] 删 `ORM.py`、处理限流器去留（§4.2）
- [ ] 打通 prompt 注入，让 AI 认识用户（§6）
- [ ] 搭 LangGraph 状态机取代 stream_chat（§7）
- [ ] 定状态机工具清单 + checkpointer 存储选型（§7）
- [ ] 落地 RAG 链路拆分（Rust /search + /index，§2）
- [ ] 定 embedding 来源 / 向量库 / rerank 取舍（§2）
- [ ] 定双模式人设方案（roleplay/code 人设卡切换，§7）
- [ ] 设计代码工具集 + human-in-the-loop 审批流程（§7）
- [ ] 阶段 0 剩余项（测试 / Compose / config 改造 / README）
- [ ] LICENSE 选型

---

## 十二、Agent 演进路线（2026-09-07 架构讨论沉淀）

> ⚠️ **本章的"路线 A（子代理 = 工具 / `as_tool`）"决策已于 2026-09-11 被 §十四 修正。** 先读 §十四 再读本章。

> 定位：当前 `graph.py` 是**单智能体 ReAct**（furina 节点 + 全量 tools）。中期目标是升级为**层级 supervisor**：主管管着编程助手 / ComfyUI / 后续组件。当务之急是先**跑通当前单图流程**，架构演进是目标不是现在的阻塞。

### 目标架构（supervisor pattern，决策已定）
- 主管 = 监工 + 任务分配 + 唯一与用户交互；子代理各自独立执行、完成汇报。
- 选型走 **A 路线（子代理 = 工具，tool-as-agent）**：主管工具清单里每个子代理是一个工具封装，天然上下文隔离、加组件 = 加一个工具。
  - 何时切 B（子代理 = 子图节点）：出现"主管必须看子代理内部状态 / 打断它"的需求时再局部切。
- 各子代理**工具按域拆分**（coder 绑代码工具、comfyui 绑图 API、主管 = 子代理 + 少量全局如搜索），禁止回到"全工具绑一个节点"。

### 关键设计待落地项（写代码前的 checklist）
- [ ] 事件契约从 `status` 魔法串 → `type` 封闭事件集（含 `error` 终态 / 工具与文本隔离 / 子代理事件带 agent 归属），错误以终态事件送达而非断流
- [ ] 错误捕获三层：节点内自愈（工具错误喂回 LLM，非图故障）→ LangGraph retry/timeout（`set_node_defaults`）→ 流边界（启动前 raise 非 200 / 流中 yield error 事件）
- [ ] supervisor 路由：第一版主管 LLM 看子代理工具 description 自选即可，不搞复杂意图路由；保留确定技能直通口，主管不做无谓中转
- [ ] 异步"丢后台"（用户离开回来要结果）→ **v2**，走 interrupt / 断点续跑或独立任务表；v1 用同步 supervisor + 流式进度（用户看着子代理进度等），慢≠必须异步
- [ ] human-in-the-loop 放子代理内层

### 当前阶段：跑通流程（回去后硬性验证清单）
- [ ] 后端 + PG/Redis 起服务，注册 → 登录（form 编码）
- [ ] `POST /agent/threads` 建线程 → `GET /agent/threads` 列表（原缺 await 已修）
- [ ] `POST /agent` 用同 thread_id 发消息 → 用 `agent_demo.html`（项目根）观察 SSE 原始帧，确认多轮续聊 + checkpoint 落库
- [ ] `DELETE /agent/threads/{id}` 后查 checkpoints 三表 0 残留（孤儿 bug 动态盖章）
- [ ] 非法 chat_thread_id → 422（强类型验收）

---

## 十三、并行项目：化学结构识别 Agent（2026-09-10 立项）

> **独立新项目**，非 furina-agent 模块；复用本项目已验证的**工具契约分层**与**LangGraph 子图编排**思路。
> 完整提案见 **`docs/2026-09-10-化学结构识别Agent-提案.md`**
> 定位：**求职旗舰作品**（与 Fabric 模组项目并列），用户本人有真实痛点。

### 一句话
教材/论文里的化学结构图 → 键线式识别 → RDKit 验证 → 一致性仲裁 → 教材 RAG → 带引用的解释。

### 已被本提案修正的既有认知（注意，与本 PLAN 其他章节相关）

| 认知 | 修正 |
|---|---|
| "复用 furina-agent 的沙箱抽象" | 现有 `BaseFileTool._resolve` 只是**路径越界守卫（权限边界）**，非进程级沙箱。化学链路需要的是**进程隔离 + 强类型领域状态**，属于新增而非继承 |
| `State{messages}` 单字段 | 不满足领域状态需求（候选分子/验证报告/仲裁结果/检索上下文）→ **新项目第一件事是改状态模型** |
| 进程隔离粒度 | 原设想"每引擎一进程" → 实测 CUDA context 每进程 300-600MB，**修正为按框架分层隔离** |

### 关键结论（已核实）
- **MolScribe**（PyTorch，Swin-Base）为主引擎；**RxnScribe 内部已调 MolScribe**，可能免去双引擎编排
- **DECIMER 是 TF 栈**，本机 Strix Halo 上**只能 CPU**（ROCm TF 版本矩阵停在 6.1.x，且 WSL2 DXG 路径另有问题）
- **chembl_structure_pipeline 入参是 molblock 不是 SMILES**，而 MolScribe 恰好返回 molfile → 天然对接口
- **全化学栈仅需 4-5GB 显存**，8GB N 卡足够。**借学校算力的理由应是 LLM/批量评测，不是 OCSR**

### 本机环境坑（Strix Halo 专属，详见提案 §6）
- 🔴 `total_memory` 报的是 **VRAM + GTT 之和**（ROCm#6004），按它算 batch 会 OOM
- 🔴 "48GB UMA" 是误导——官方：走 GPUVM，**ROCm pool 受 `.wslconfig` memory 限制**（ROCm#6022）
- 🟠 UMA 下 CPU 与 GPU **抢同一条内存总线** → 双引擎并行可能比串行更慢
- 🟠 子进程拿不到 `HSA_ENABLE_DXG_DETECTION` / `HF_ENDPOINT` → **进程隔离架构的必经坑**

### 待办追踪（下次开工从这挑）

> ⚠️ **提醒：写任何项目代码前，先跑完提案 §7 的 9 个验证实验。**

- [ ] 查 `.wslconfig`，确认 WSL2 内存上限（实验 1）
- [ ] 二分探测最大可分配张量，与 `total_memory` 对比（实验 2+3）
- [ ] `pip install MolScribe`，确认 `predict_images` 真实签名与返回字段（实验 9-②）
- [ ] 确认 `chembl_structure_pipeline.standardize_*` 的幂等性（实验 9-③）
- [ ] MolScribe CPU vs ROCm GPU 结果一致性比对（实验 7，**防算子精度偏差**）
- [ ] DECIMER(CPU) + MolScribe(GPU) 并行 vs 串行计时（实验 8）
- [ ] 决定 ChromaDB vs pgvector（`VectorStore` 抽象先留着）
- [ ] 确认 `pip install MolScribe` 是否顶掉 ROCm torch（INV-3）

### 未决问题（待拍板）
Q1 RxnScribe 内置 MolScribe 后双引擎仲裁是否还成立 ｜ Q2 MolScribe confidence 的校准如何验证 ｜ Q3 并行更慢时双引擎策略 ｜ Q4 `max_batch_size` 定值方式 ｜ Q5 HITL 结果是否回写成 eval 数据 ｜ Q6 BGE-M3 CPU 吞吐是否够批量入库 ｜ Q7 向量库选型 ｜ Q8 教材语料版权 ｜ Q9 学校机器断连时的降级通路
（完整描述见提案 §10）

---

## 十四、架构决策：弃用 `create_agent`，改手搓 StateGraph（2026-09-11）

> 一句话：`create_agent` 的图结构是固定的（`model ↔ tools` 循环），**加不了自定义节点和条件边**，装不下 §七 的节点清单；且 HITL 的审批对象需要 `path + diff`，middleware 给不了结构化载荷。**改手搓。**

### 14.1 决策

| 组件 | 原方案 | 新方案 |
|---|---|---|
| **主管 supervisor** | `create_agent()` | **手搓 `StateGraph`**：自定义节点 + 条件边 |
| **coder 子代理** | `create_agent(name="coder")` | **手搓 ReAct 循环**（model 节点 + tools 节点 + 条件边） |
| **子代理形态** | `coder.as_tool()` 包成工具（§十二 路线 A） | **待定** —— 见 14.4，倾向手搓后改走子图节点 |
| **HITL 审批** | `HumanInTheLoopMiddleware` | **`interrupt()` 内嵌进自写 `BaseTool`**（回到 §9.8 落地决策 #3） |
| **写文件工具** | 沿用 | 自写 `BaseTool` 子类（已在做，`_resolve` 已完成） |

### 14.2 三条理由

**① 表达能力不够（决定性）**
§七 列了五个节点：用户画像注入 / 意图路由 / RAG 检索 / LLM 生成 / 持久化。
`create_agent` 只能塞 middleware 或 system_prompt，绕且别扭。**需求本身已超出它。**

**② 差异化点（diff 预览）需要工具内 `interrupt()`**
middleware 的 `description` 可以传 callable 去算 diff，但返回类型是 **`str`** —— diff 只活在显示字符串里。
其结构化载荷只有 `action_requests: [{name, args, description}]`，且 `edit` 改的是 `args`（整份内容），不是 diff。
**要结构化 `{path, diff, old_hash}`，只有工具内 `interrupt()` 能给。**

**③ 排障与对齐文档**
自己画的图 = 画得出时序图。`create_agent` 是黑盒，middleware 的 `after_model` 在循环哪一步必须读源码才知道。
且**官方 HITL 文档（`/oss/python/langgraph/interrupts`）本身就是讲手搓图的** —— 手搓后与文档零摩擦。

> ⚠️ 认知纠偏：中文教程"大多用手搓"**不代表手搓更好**，而是中文资料滞后于 LangChain v1 的 API 演进。理由只能是上面的 ①②③，不能是"教程这么写"。

### 14.3 要认的成本

手搓 = ReAct 循环自己写。`create_agent` 白送的三样：

| 白送的东西 | 自写难度 |
|---|---|
| `model → tools` 条件边 + 循环 | 不高 |
| messages reducer | 不高 |
| **ToolNode 的并发 + 错误处理** | **有讲究** —— 「工具抛异常不能崩图」需自己兜（呼应 9.10 结论：`_run` 错误必须转字符串返回） |

### 14.4 对 §十二 的连带修正（路线 A/B 重新拍板）

§十二 原定 **A 路线（子代理 = 工具，`as_tool`）**，理由是"天然上下文隔离、加组件 = 加一个工具"。

**手搓之后多了一个选项**：coder 做成**子图节点**（B 路线），中断靠 **namespace 嵌套天然冒泡**，**整个绕开 `as_tool` 的 beta 风险与冒泡不确定性**。

| | A 路线（`as_tool`） | B 路线（子图节点） |
|---|---|---|
| 上下文隔离 | 好 | 需自行设计 state 才隔离 |
| 中断冒泡 | **待验证**（见 §十四.6） | 天然 |
| API 稳定性 | **beta** | 稳定 |
| 加组件成本 | 加一个工具 | 加一个节点 |

→ **待拍板**：倾向 **B 路线**（手搓后 A 路线的唯一优势"少写代码"已不成立，而它带来两项不确定性）。

### 14.5 重构清单（按依赖序）

- [ ] **1. `state.py`** —— `State` 从 `messages` 单字段 → 强类型领域状态（至少含 `messages` / `mode` / 用户画像位）
      ⚠️ 现状是 Pydantic `BaseModel`；LangGraph 的 `StateGraph` 对 `TypedDict` 支持更顺，**需先拍板用哪个**
- [ ] **2. `node/coder.py`** —— `create_agent` → 手搓 ReAct 循环（model 节点 + tools 节点 + 条件边）
- [ ] **3. `node/coder_tools.py`** —— `ReadFileTool` / `WriteFileTool` 补齐 `_run`；**写入工具内嵌 `interrupt()`**
- [ ] **4. `graph.py`** —— `create_agent` supervisor → 手搓 `StateGraph`（§七 的五节点 + 条件边）
- [ ] **5. `services/agent_stream.py`** —— `stream_mode="messages"` → `["messages","values"]`，接住 `interrupts`
- [ ] **6. `tools.py`** —— `tool_node = ToolNode(...)` 目前是模块级单例且只含 `bocha_search_tool`，重构时一并处理

### 14.6 必须保留的验证实验

`docs/9.11-子代理中断冒泡验证.md` —— **如果最终选 B 路线（子图节点），实验 A 仍需做**，但意义从"验证 `as_tool`"变成"验证子图嵌套下中断冒泡 + 单入口恢复"。

### 14.7 已核实的版本事实（2026-09-11，本机 `.venv`）

| 事实 | 出处 |
|---|---|
| `langchain 1.3.18` / `langgraph 1.2.11` | `importlib.metadata` 实测 |
| **中断不会被误判成 tool-error** | `pregel/_runner.py:591-598`，`GraphInterrupt` / `GraphBubbleUp` 与真错误分流 |
| `create_agent` 签名含 `middleware=` / `interrupt_before=` | 实测（虽已弃用，留档） |
| `astream` 的 `version` 只接受 `v1`/`v2`，**不接受 v3** | `Pregel.astream` 签名 |
| `stream_events(version="v3")` 是 **experimental** | `Pregel.stream_events` 源码警告 |
| `StateSnapshot` 含 `interrupts` / `next` 字段 | 本机实测 |

### 14.8 开放问题（写代码前定）

- **Q1** `State` 用 `TypedDict` 还是 Pydantic `BaseModel`？（现状是 BaseModel）
- **Q2** coder 走 A 路线还是 B 路线？（见 14.4，倾向 B）
- **Q3** 手搓的 ReAct 循环，工具错误处理是自己写还是复用 `ToolNode`？（复用可省事，但 `ToolNode` 是否限制后续扩展待验）
- **Q4** diff 预览：工具内 `interrupt()` 读旧文件算 diff —— 旧文件读不到（新建）时 payload 长什么样？
- **Q5** §七 的"意图路由"用规则优先还是 LLM 优先？（原 PLAN 写"规则优先，LLM 兜底"）

---

## 十五、暂缓登记（技术减法容器）

> **用途**：把"想做、但今天不该做"的东西放这里。**登记 ≠ 否决**，是"挂起 + 标明触发条件"。
> **目的**：让"不做"变成一个**有据可查的决定**，而不是每次靠意志力硬扛。
> **规则**：每条必须写清 ① 是什么 ② 为什么现在不做 ③ 什么条件下捡起来。

| # | 暂缓项 | 登记日期 | 状态 |
|---|---|---|---|
| D-1 | 用 `Literal + Enum + @dataclass` 手搓类 Rust 枚举（ADT） | 2026-09-15 | ⏸ 挂起 |

### D-1 · 手搓 Rust 式枚举（ADT）

**想法**：用 `Literal` + `Enum` + `@dataclass` 三件套，在 Python 里模拟 Rust `enum` 的"带数据变体 + 穷尽性匹配"。

**动机（真实且合理）**：出自 `backend/app/schemas/model.py:109` 自己写的注释 —— `Literal` 只是静态检查，给不了 Rust 那种"类型不对就报错"的强制力。这个不满是准确的。

**为什么现在不做**

1. **没有调用者**：`ApprovalRequest` / `RejectionPayload` 目前是**悬空**的 —— `agent/graph.py:100-102` 的 `build_graph` 仍是 stub，HITL 一次都没跑通过。给没有真实载荷流过的类型升级表达力 = 给没打地基的房子挑窗帘。
2. **Python 差的是最后一层，且补不上**：Rust enum 的强制力来自**编译器**。Python 的类型检查是**可选的** —— 不装 mypy、不写 `assert_never`，那套 ADT 毫无约束力。这是**语言层面的赤字，不是库层面的**。
3. **Pydantic 已经到顶了**：判别联合是原生能力，不需要手搓。
4. **机会成本**：会挤掉 HITL 验收的时间 —— 而 HITL 跑通是**求职面试素材**，手搓 ADT 不是。

**触发条件（满足才捡起来）**

> HITL 已跑通，**且**出现**第二种形状完全不同**的审批载荷 —— 例如"shell 命令审批"（命令 / cwd / timeout）与"文件写入审批"（path / diff / old_hash）字段完全不搭边、`Literal` 撑不住时。

**捡起来时的执行要点（避免重新踩坑）**

- ✅ 正确形状 = Pydantic 判别联合 `Annotated[A | B, Field(discriminator="type")]`，**不是**三件套手搓
- ⚠️ `Literal` 与 `Enum` 是**同一功能的两种写法** —— 二选一。项目里两种都有（`model.py:25` / `state.py:26`），但**从未叠加过**，别开先例
- ✅ 穷尽性检查在 Python 里只有一条路：`match` + `typing.assert_never()`（3.11+），**且只在 mypy / pyright 下生效**，运行时仅抛异常
- ❌ `@dataclass` 直接出局：interrupt 载荷**必须 JSON 可序列化**
- 📌 想真身体验 ADT 的强制力 → 去 Rust 里写（见 `docs/rust-notes/`），Python 给不了这个体感

**顺带记录（本次讨论的副产品）**

- 🐛 `backend/app/schemas/model.py:109` 注释有误：「只是静态检查」对**裸类型注解**成立，对 **Pydantic 字段不成立** —— Pydantic 是运行时校验器，`ApprovalRequest(risk_level="critical")` 会当场 `ValidationError`。
- 🔴 `model.py:111` / `:118` 两处 `action: str` 无任何取值约束，是当前 HITL 载荷最大的洞（属 §十四 契约裁决范围，见 9.15 清单「事项 2.1」）。

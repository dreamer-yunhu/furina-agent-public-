# ADR：T19 变更——新增受约束的 `RUNNING → SUSPENDED`

> 状态：**已确认并实施**（2026-10-24；`smoke_lifecycle.py` 74/74）
> 日期：2026-10-24 ｜ 触发：T22 决策确认单 Q11=B
> 范围：仅 T19 迁移边、入口约束、语义与测试设计；**本轮不改代码**

---

## 1. 背景与问题

T22 的恢复流程是：

```
校验通过 → DB 迁移到 RUNNING → 图 resume
```

数据库与 LangGraph checkpoint 不是同一事务。若 DB 已经 `RUNNING`、图 resume 失败，当前**没有回退路径**：

- T19 迁移表只有 `RUNNING → WAITING_APPROVAL / COMPLETED / FAILED / CANCELLED`
- 没有 `RUNNING → SUSPENDED`
- 置 `FAILED` 会把一次基础设施故障变成任务终态（T22 Q11=A 的代价）

决策确认单选择 **B**：为 T19 增加**经过约束**的 `RUNNING → SUSPENDED`，保留可重试路径。

---

## 2. 现状事实

| # | 事实 | 证据 |
|---|---|---|
| F1 | Task 迁移表：`RUNNING → {WAITING_APPROVAL, COMPLETED, FAILED, CANCELLED}` | `lifecycle.py:29-45` |
| F2 | Execution 迁移表同上，另有 `VALIDATION_FAILED` | `lifecycle.py:49-72` |
| F3 | `SUSPENDED` 当前只有一种进入方式：`WAITING_APPROVAL → SUSPENDED`（T21） | `timeout_scanner.py:116-131` |
| F4 | 迁移函数是 CAS + 同事务；`transition_pair` 要求无活动事务的 Session | `lifecycle_service.py:99-160` |
| F5 | `TransitionOutcome` 有 APPLIED/ILLEGAL/CONFLICT/NOT_FOUND/SCOPE_MISMATCH | `lifecycle.py:20-27` |
| F6 | 没有 `suspend_reason` 字段；`Task.failure_reason` 只用于 FAILED；`Execution.validation_failure_reason` 语义是校验失败 | `models.py:78/114` |
| F7 | 无 Alembic；`create_all` 只建新表，不改旧表列 | `docs/TODO.md` Q6、`database.py` |
| F8 | T21 扫描查询要求审批 PENDING + 到期，且排除两边都已 SUSPENDED 的对 | `repository.py:list_due_pending_approvals` |

---

## 3. 方案对比

| 选项 | 做法 | 后果 |
|---|---|---|
| A | 不加边；resume 失败置 `FAILED` | 终态；一次故障需要 T24 重委派 |
| B | 直接把 `RUNNING→SUSPENDED` 加进通用迁移表 | 任何调用方都能把运行中的任务挂起，可能自由振荡 |
| **C（推荐）** | 加边，但标记为**受保护边（guarded）**；只有专用入口在完成前置校验后才能迁 | 保留可重试路径，且默认 API 拒绝该边 |
| D | 新增状态 `SUSPENDED_RESUME_FAILED` | 违反“不凭空增加状态”；且所有消费者都要改 |

**推荐 C。**

---

## 4. 变更设计

### 4.1 迁移表

两张表各增加一条边：

```
Task:      RUNNING → SUSPENDED   （guarded）
Execution: RUNNING → SUSPENDED   （guarded）
```

同时登记受保护边集合：

```python
GUARDED_TASK_EDGES = {(TaskStatus.RUNNING, TaskStatus.SUSPENDED)}
GUARDED_EXECUTION_EDGES = {(ExecutionStatus.RUNNING, ExecutionStatus.SUSPENDED)}
```

### 4.2 为什么需要 guarded

仅把边加进表里，`transition_task/execution` 与 `transition_pair` 就都能直接使用它。
这会让“挂起运行中的任务”变成随意操作，并与 `SUSPENDED→RUNNING` 形成无约束振荡。

**约束方式**：

- `repository.transition_task/execution` 增加 `guarded_ok: bool = False`
  - 如果 `(from, to)` 在 guarded 集合且 `guarded_ok=False` → 直接拒绝（返回 False）
- `lifecycle_service.transition_pair` 增加 `guarded_ok: bool = False`，判断放在 CAS 之前，返回 `(ILLEGAL, CONFLICT)` / `(CONFLICT, ILLEGAL)`
- 现有调用默认 `False`，行为不变

### 4.3 专用入口

```python
class SuspendReason(str, Enum):
    APPROVAL_TIMEOUT = "APPROVAL_TIMEOUT"   # 供 T21 语义对齐，不由此入口使用
    RESUME_FAILED = "RESUME_FAILED"         # 由 T23 在 resume 失败时使用

async def suspend_after_resume_failure(
    session: AsyncSession,
    *,
    task_id: uuid.UUID,
    execution_id: uuid.UUID,
    reason: SuspendReason = SuspendReason.RESUME_FAILED,
) -> tuple[TransitionOutcome, TransitionOutcome]:
    ...
```

**前置校验（全部满足才迁移）**：

1. Task 与 Execution 都存在且归属一致
2. 两者当前状态均为 `RUNNING`
3. 该 Execution 下**所有审批**的 `tool_execution_status == NOT_STARTED`
   - 任一为 `RUNNING/SUCCEEDED/FAILED/UNKNOWN` → 拒绝
4. 调用 `transition_pair(RUNNING → SUSPENDED, guarded_ok=True)`

**为什么第 3 条是硬条件**：一旦工具已经开始或有副作用，挂起后重试可能重复执行；
`UNKNOWN` 更是明确“可能已产生副作用”。这类情况只能 `FAILED`，不能进入可重试的 `SUSPENDED`。

### 4.4 `SUSPENDED` 的两种来源

| 来源 | 进入边 | 恢复条件 |
|---|---|---|
| 审批超时（T21） | `WAITING_APPROVAL → SUSPENDED` | T22 校验：批准、无 PENDING、工具未执行、文件未变 |
| 恢复失败（T23） | `RUNNING → SUSPENDED`（guarded） | 同上；且必须仍然没有任何工具执行过 |

T22 的恢复校验对两种来源是**同一套规则**，不需要区分来源。
但来源影响**升级策略**：`RESUME_FAILED` 若再次失败且工具仍未执行，可以继续重试；是否限制次数见 §8。

### 4.5 挂起原因是否持久化

| 选项 | 做法 | 代价 |
|---|---|---|
| **A（推荐）** | 不新增列；`SuspendReason` 只用于返回值与日志 | 无法按原因查询；但零迁移、零 Schema 风险 |
| B | 复用 `Task.failure_reason` / `Execution.validation_failure_reason` | 字段语义被污染（它们分别属于 FAILED / 校验失败） |
| C | 新增 `suspend_reason` 列 | 最干净，但当前无 Alembic，`create_all` 不会给已有表加列 → 必须引入迁移工具 |

**推荐 A**。原因查询需求出现时，再单独做 Schema ADR（含 Alembic）。

---

## 5. 事务、并发与失败语义

- 迁移仍走 `transition_pair`：CAS + 同一事务，任一侧失败整体回滚
- 第二次 `RUNNING→SUSPENDED`：当前已不在 `RUNNING` → `CONFLICT`（不会重复生效）
- 专用入口的查询（审批执行状态）与迁移分属两次读/写；窗口内若有工具被认领，CAS 不会阻止挂起
  → **这是残余风险**，缓解手段：迁移前再查一次审批状态；仍不能彻底消除（跨表）
- 图恢复失败与 DB 挂起之间没有事务关系；T23 需要按“先迁移、后 resume、失败再挂起”的顺序编排

---

## 6. 对 T21 / T22 / T23 / T24 的影响

| 阶段 | 影响 |
|---|---|
| T21 | 无行为变化；它继续只用 `WAITING_APPROVAL→SUSPENDED`；查询已排除两边 SUSPENDED 的对 |
| T22 | 恢复校验无需区分 `SUSPENDED` 来源；Q11 的前置由本 ADR 满足 |
| T23 | 在 resume 失败时调用 `suspend_after_resume_failure`；若工具已开始则改走 `FAILED` |
| T24 | 若最终判定不可重试，仍由 T24 新建 Task 重委派 |

---

## 7. 测试计划（T19 变更实施时）

1. 迁移矩阵：`RUNNING→SUSPENDED` 在表中存在且标记为 guarded
2. 通用 `transition_task/execution` 不带 `guarded_ok` → 拒绝该边
3. `transition_pair` 不带 `guarded_ok` → `ILLEGAL`
4. 专用入口：Task/Execution 均 RUNNING、工具全 `NOT_STARTED` → 成对 `APPLIED`
5. 专用入口：任一审批 `RUNNING/SUCCEEDED/FAILED/UNKNOWN` → 拒绝，状态不变
6. 专用入口：Task 或 Execution 不是 RUNNING → 拒绝
7. 归属不匹配 → `SCOPE_MISMATCH`
8. 重复调用 → `CONFLICT`，状态不变
9. 失败注入（第二次迁移失败）→ 两表都不变
10. 既有 T19 矩阵测试更新：显式断言新边；其余边不变
11. T21 扫描器回归（应完全不受影响）
12. T22 恢复服务回归（在其实现后）

---

## 8. 需要确认的问题

| # | 问题 | 推荐 |
|---|---|---|
| Q-T19-1 | 是否同意“加边 + guarded 集合 + 专用入口”的方案 C？ | 是 |
| Q-T19-2 | 是否同意 guarded 约束下沉到 repository（新增 `guarded_ok` 参数，默认 False）？ | 是 |
| Q-T19-3 | 是否同意挂起原因本轮不持久化（仅返回值/日志）？ | 是 |
| Q-T19-4 | 专用入口是否只允许 `reason=RESUME_FAILED`？ | 是（`APPROVAL_TIMEOUT` 仍由 T21 走原边） |
| Q-T19-5 | 是否限制重试次数？ | 本轮不限制（无字段）；每次由 T23 显式触发 |
| Q-T19-6 | 工具状态为 `UNKNOWN` 时是否一律拒绝挂起、改走 `FAILED`？ | 是 |

---

## 9. 实施顺序（确认后）

1. 更新 `lifecycle.py`：加边 + guarded 集合
2. 更新 `repository.transition_*` / `lifecycle_service.transition_pair`：`guarded_ok`
3. 新增 `SuspendReason` 与 `suspend_after_resume_failure`
4. 更新/新增 `smoke_lifecycle.py` 用例（§7）
5. 全量回归
6. 之后才进入 T22 恢复服务实现

**本轮不动代码。**

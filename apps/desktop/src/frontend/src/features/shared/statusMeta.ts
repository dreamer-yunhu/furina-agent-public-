// ── AI-ASSISTED ── 本文件由 AI 生成/改写，待人工复核 ──
// 复核重点：
//   1. ★ 本文件原来映射的是 demo 的小写状态（idle/running/completed...）。
//      删除 demo 后，唯一可信的状态源是后端枚举（`furina_core.task.enums`）。
//      键必须与后端**逐字一致**（全大写），否则界面会显示原始英文枚举。
//   2. 审批状态与工具执行状态是两套独立字段，别合并。
//   3. 未知值统一走 `statusMeta(map, value)` 的兜底：显示原值 + neutral，
//      不猜测、不隐藏 —— 后端新增枚举时前端应该"显示得难看"而不是"看起来正常"。

import type { StatusTone } from '../../components/ui/StatusPill'

export interface StatusMeta {
  label: string
  tone: StatusTone
}

/** 业务任务状态（后端 TaskStatus） */
export const TASK_STATUS_META: Record<string, StatusMeta> = {
  QUEUED: { label: '排队中', tone: 'neutral' },
  RUNNING: { label: '运行中', tone: 'running' },
  WAITING_APPROVAL: { label: '等待审批', tone: 'warning' },
  SUSPENDED: { label: '已挂起', tone: 'danger' },
  COMPLETED: { label: '已完成', tone: 'success' },
  FAILED: { label: '失败', tone: 'danger' },
  CANCELLED: { label: '已取消', tone: 'neutral' },
}

/** 执行状态（后端 ExecutionStatus） */
export const EXECUTION_STATUS_META: Record<string, StatusMeta> = {
  CREATED: { label: '已创建', tone: 'neutral' },
  RUNNING: { label: '执行中', tone: 'running' },
  WAITING_APPROVAL: { label: '等待审批', tone: 'warning' },
  SUSPENDED: { label: '已挂起', tone: 'danger' },
  VALIDATION_FAILED: { label: '恢复校验失败', tone: 'danger' },
  COMPLETED: { label: '已完成', tone: 'success' },
  FAILED: { label: '失败', tone: 'danger' },
  CANCELLED: { label: '已取消', tone: 'neutral' },
}

/** 审批决定（后端 ApprovalStatus）—— 与工具执行状态是两回事 */
export const APPROVAL_STATUS_META: Record<string, StatusMeta> = {
  PENDING: { label: '待审批', tone: 'warning' },
  APPROVED: { label: '已批准', tone: 'info' },
  REJECTED: { label: '已拒绝', tone: 'danger' },
  REVOKED: { label: '已撤销', tone: 'neutral' },
}

/** 工具实际执行（后端 ToolExecutionStatus） */
export const TOOL_EXECUTION_META: Record<string, StatusMeta> = {
  NOT_STARTED: { label: '未开始', tone: 'neutral' },
  RUNNING: { label: '执行中', tone: 'running' },
  SUCCEEDED: { label: '执行成功', tone: 'success' },
  FAILED: { label: '执行失败', tone: 'danger' },
  UNKNOWN: { label: '结果未知', tone: 'warning' },
}

/** 未知枚举值的兜底：原样显示，不假装认识。 */
export function statusMeta(
  map: Record<string, StatusMeta>,
  value: string | null | undefined,
  fallbackLabel = '未知',
): StatusMeta {
  if (!value) return { label: fallbackLabel, tone: 'neutral' }
  return map[value] ?? { label: value, tone: 'neutral' }
}

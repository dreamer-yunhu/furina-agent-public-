// ── AI-ASSISTED ── 本文件由 AI 生成，待人工复核 ──
// 复核重点：状态文案/语气集中在这里，避免审批卡片、任务列表、审计页各写一份。

import type { StatusTone } from '../../components/ui/StatusPill'
import type {
  DemoApprovalStatus,
  DemoRisk,
  DemoRunStatus,
  DemoToolStatus,
} from '../../demo/types'

export interface StatusMeta {
  label: string
  tone: StatusTone
}

export const APPROVAL_STATUS_META: Record<DemoApprovalStatus, StatusMeta> = {
  pending: { label: '待审批', tone: 'warning' },
  approved: { label: '已批准', tone: 'info' },
  rejected: { label: '已拒绝', tone: 'danger' },
}

export const TOOL_STATUS_META: Record<DemoToolStatus, StatusMeta> = {
  pending: { label: '等待执行', tone: 'neutral' },
  running: { label: '执行中', tone: 'running' },
  succeeded: { label: '执行成功', tone: 'success' },
  failed: { label: '执行失败', tone: 'danger' },
  skipped: { label: '未执行', tone: 'neutral' },
  unknown: { label: '结果未知', tone: 'warning' },
}

export const RISK_META: Record<DemoRisk, StatusMeta> = {
  low: { label: '低风险', tone: 'neutral' },
  medium: { label: '中风险', tone: 'warning' },
  high: { label: '高风险', tone: 'danger' },
}

export const RUN_STATUS_META: Record<DemoRunStatus, StatusMeta> = {
  idle: { label: '未开始', tone: 'neutral' },
  running: { label: '执行中', tone: 'running' },
  waiting_approval: { label: '待审批', tone: 'warning' },
  completed: { label: '已完成', tone: 'success' },
  failed: { label: '失败', tone: 'danger' },
}

// ── AI-ASSISTED ── 本文件由 AI 生成，待人工复核 ──
// 复核重点：这些类型只服务于**演示数据**，不要把它们当成后端 DTO。
// 真实接入时应在 services/api 下另建类型，不能直接复用 Demo 类型。

export type DemoRunStatus =
  | 'idle'
  | 'running'
  | 'waiting_approval'
  | 'completed'
  | 'failed'

export type DemoApprovalStatus = 'pending' | 'approved' | 'rejected'

export type DemoToolStatus =
  | 'pending'
  | 'running'
  | 'succeeded'
  | 'failed'
  | 'skipped'
  | 'unknown'

export type DemoRisk = 'low' | 'medium' | 'high'

export interface DemoThread {
  id: string
  title: string
  preview: string
  updatedAt: string
  status: DemoRunStatus
  pendingApprovals: number
}

export interface DemoToolCall {
  id: string
  name: string
  target: string
  status: DemoToolStatus
  summary: string
  at: string
}

export interface DemoExecution {
  id: string
  taskId: string
  status: DemoRunStatus
  startedAt: string
  finishedAt?: string
  summary: string
  toolCalls: DemoToolCall[]
}

export interface DemoApproval {
  id: string
  threadId: string
  taskId: string
  executionId: string
  toolName: string
  target: string
  summary: string
  risk: DemoRisk
  status: DemoApprovalStatus
  requestedAt: string
  decidedAt?: string
  decidedBy?: string
  decisionReason?: string
  toolExecutionStatus: DemoToolStatus
  toolResult?: string
}

export interface DemoTask {
  id: string
  threadId: string
  title: string
  status: DemoRunStatus
  updatedAt: string
  executions: DemoExecution[]
  approvalIds: string[]
}

export interface DemoMessage {
  id: string
  role: 'user' | 'assistant' | 'system'
  content: string
  at: string
  toolCalls?: DemoToolCall[]
  approvalId?: string
}

// ── AI-ASSISTED ── 本文件由 AI 生成，待人工复核 ──
// 复核重点：
//   1. 列表接口的 `instruction` 后端只回前 200 字，前端不要指望拿它做全文搜索。
//   2. 审批列表**不含 args_json**（可能很大），只有路径与状态。
//   3. 状态是后端枚举的**原样字符串**（如 `WAITING_APPROVAL`），
//      映射成界面文案请在展示层做，不要在这里改值。

import { apiFetch } from './client'
import type { ApiReviewRequest } from './types'

export interface ApiTaskItem {
  id: string
  thread_id: string
  thread_title: string
  instruction: string
  status: string
  created_at: string
  updated_at: string
}

export interface ApiTaskList {
  items: ApiTaskItem[]
  total: number
  page: number
  size: number
}

export interface ApiApprovalItem {
  id: string
  task_id: string
  execution_id: string
  thread_id: string
  thread_title: string
  tool_name: string
  target_path: string | null
  approval_status: string
  tool_execution_status: string
  created_at: string
  decided_at: string | null
  decision_reason: string | null
}

export interface ApiApprovalList {
  items: ApiApprovalItem[]
  total: number
  page: number
  size: number
}

export interface ApiPendingResponse {
  pending: {
    interrupt_id: string
    review: ApiReviewRequest
  } | null
}

/** 执行（后端 AgentExecution 的投影） */
export interface ApiExecutionItem {
  id: string
  task_id: string
  status: string
  graph_thread_id: string
  validation_failure_reason: string | null
  created_at: string
  finished_at: string | null
}

/** GET /agent/tasks/{id} */
export interface ApiTaskDetail extends ApiTaskItem {
  failure_reason: string | null
  executions: ApiExecutionItem[]
  approvals: ApiApprovalItem[]
}

/** GET /agent/executions/{id} */
export interface ApiExecutionDetail extends ApiExecutionItem {
  thread_id: string
  thread_title: string
  task: ApiTaskItem
  approvals: ApiApprovalItem[]
}

/** GET /agent/approvals/{id} */
export interface ApiApprovalDetail extends ApiApprovalItem {
  task: ApiTaskItem
}

/** GET /agent/tasks */
export function listTasks(
  page = 1,
  size = 20,
  threadId?: string,
): Promise<ApiTaskList> {
  const query = new URLSearchParams({ page: String(page), size: String(size) })
  if (threadId) query.set('thread_id', threadId)
  return apiFetch<ApiTaskList>(`/agent/tasks?${query.toString()}`)
}

/** GET /agent/tasks/{id} —— 详情比列表多 executions / approvals / 完整 instruction */
export function getTask(taskId: string): Promise<ApiTaskDetail> {
  return apiFetch<ApiTaskDetail>(`/agent/tasks/${encodeURIComponent(taskId)}`)
}

/** GET /agent/executions/{id} */
export function getExecution(executionId: string): Promise<ApiExecutionDetail> {
  return apiFetch<ApiExecutionDetail>(
    `/agent/executions/${encodeURIComponent(executionId)}`,
  )
}

/** GET /agent/approvals/{id} */
export function getApproval(approvalId: string): Promise<ApiApprovalDetail> {
  return apiFetch<ApiApprovalDetail>(
    `/agent/approvals/${encodeURIComponent(approvalId)}`,
  )
}

/** GET /agent/approvals */
export function listApprovals(params: {
  page?: number
  size?: number
  status?: string
  threadId?: string
} = {}): Promise<ApiApprovalList> {
  const query = new URLSearchParams({
    page: String(params.page ?? 1),
    size: String(params.size ?? 50),
  })
  if (params.status) query.set('status', params.status)
  if (params.threadId) query.set('thread_id', params.threadId)
  return apiFetch<ApiApprovalList>(`/agent/approvals?${query.toString()}`)
}

/** GET /agent/threads/{id}/pending —— 刷新后恢复审批卡用 */
export function getPending(threadId: string): Promise<ApiPendingResponse> {
  return apiFetch<ApiPendingResponse>(
    `/agent/threads/${encodeURIComponent(threadId)}/pending`,
    { timeoutMs: 8000 },
  )
}

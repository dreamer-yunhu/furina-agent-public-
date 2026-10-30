// ── AI-ASSISTED ── 本文件由 AI 生成，待人工复核 ──
// 复核重点：历史是后端按「每次执行各自的 checkpoint」拼出来的，
// 不是一张消息表；前端不要假设 id 唯一（由 state.result 补出的那条 id 为空）。

import { apiFetch } from './client'
import type { ApiMessageList } from './types'

/** GET /agent/threads/{threadId}/messages */
export function listMessages(threadId: string): Promise<ApiMessageList> {
  return apiFetch<ApiMessageList>(
    `/agent/threads/${encodeURIComponent(threadId)}/messages`,
    { timeoutMs: 8000 },
  )
}

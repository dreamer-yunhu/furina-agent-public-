// ── AI-ASSISTED ── 本文件由 AI 生成，待人工复核 ──
//
// 审批链路。后端是**两步**，前端不能合成一步：
//
//   ① POST /agent/decisions  把决定落库（T20 服务，幂等）
//   ② POST /agent/resume     用 ReviewDecision 恢复图，并继续流式
//
// 为什么必须分开：decisions 只落库不跑图；resume 只跑图不落库。
// 先落库再续跑，图崩溃时决定仍然可查 —— 顺序反了会丢审计。
//
// 复核重点：
//   1. resume 要求 decisions **与挂起项逐条对齐**（后端 check_decision_matches），
//      少一条/多一条/重复都会 409。所以 UI 必须收齐所有裁决再提交。
//   2. 这里不做重试：409 多半是"决定与挂起项不匹配"，重试只会再 409。

import { apiFetch } from './client'
import { postSse, readSse } from './chat'
import type {
  AgentEvent,
  ApiItemDecision,
  ApiReviewDecision,
} from './types'

export interface DecisionResponse {
  execution_id: string
  results: unknown[]
}

/** 第一步：落库。 */
export function submitDecisions(
  chatThreadId: string,
  decisions: ApiItemDecision[],
): Promise<DecisionResponse> {
  return apiFetch<DecisionResponse>('/agent/decisions', {
    method: 'POST',
    body: JSON.stringify({
      chat_thread_id: chatThreadId,
      decisions,
    }),
  })
}

/** 第二步：恢复并继续流式。 */
export async function* resumeChat(
  chatThreadId: string,
  decisions: ApiItemDecision[],
  signal?: AbortSignal,
): AsyncGenerator<AgentEvent> {
  const review: ApiReviewDecision = {
    type: 'review_decision',
    decisions,
  }
  const response = await postSse(
    '/agent/resume',
    { chat_thread_id: chatThreadId, review },
    signal,
  )
  yield* readSse(response)
}

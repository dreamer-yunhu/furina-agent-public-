// ── AI-ASSISTED ── 本文件由 AI 生成，待人工复核 ──
// 复核重点：这一层只做「路径 + 参数 → DTO」，不放业务判断。
// 后端分页参数是 page/size（size 上限 100），别改成 offset/limit。

import { apiFetch } from './client'
import type { ApiThreadList } from './types'

/** GET /agent/threads */
export function listThreads(page = 1, size = 20): Promise<ApiThreadList> {
  const query = new URLSearchParams({ page: String(page), size: String(size) })
  return apiFetch<ApiThreadList>(`/agent/threads?${query.toString()}`)
}

/** 创建线程的响应（后端只回 id/title/created_at） */
export interface CreatedThread {
  id: string
  title: string
  created_at: string
}

/** POST /agent/threads —— title 上限 255 */
export function createThread(title: string): Promise<CreatedThread> {
  return apiFetch<CreatedThread>('/agent/threads', {
    method: 'POST',
    body: JSON.stringify({ title }),
  })
}

/** PATCH /agent/threads/{id} —— 改标题 */
export function renameThread(threadId: string, title: string): Promise<unknown> {
  return apiFetch(`/agent/threads/${encodeURIComponent(threadId)}`, {
    method: 'PATCH',
    body: JSON.stringify({ title }),
  })
}

/** DELETE /agent/threads/{id} —— 同时删 checkpoint（后端会 adelete_thread） */
export function deleteThread(threadId: string): Promise<unknown> {
  return apiFetch(`/agent/threads/${encodeURIComponent(threadId)}`, {
    method: 'DELETE',
  })
}

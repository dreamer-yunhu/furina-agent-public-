// ── AI-ASSISTED ── 本文件由 AI 生成，待人工复核 ──
// 复核重点：
//   1. `POST /agent` 返回的是 SSE（text/event-stream），不是普通 JSON。
//      不能等 `res.json()`，必须读 body 流并按 `\n\n` 切帧。
//   2. 帧格式固定为 `data: {...}\n\n`；未知类型直接跳过，不抛错
//      （后端新增事件时旧前端不应崩）。
//   3. **不设总超时**：一次 Agent 运行可能几分钟。取消靠 AbortSignal，
//      由调用方在组件卸载/用户中止时触发。
//
// 这是 async generator，调用方用 `for await` 消费。

import { API_BASE_URL } from './config'
import { ApiError } from './client'
import type { AgentEvent } from './types'

export interface ChatRequest {
  /** 后端限制 1–255 字符（api/contracts.py 的 AgentRequest） */
  user_input: string
  chat_thread_id: string
  model?: string
}

function parseFrame(raw: string): AgentEvent | null {
  for (const line of raw.split('\n')) {
    if (!line.startsWith('data:')) continue
    const payload = line.slice(5).trim()
    if (!payload) continue
    try {
      const parsed = JSON.parse(payload) as AgentEvent
      if (parsed && typeof parsed === 'object' && 'type' in parsed) return parsed
    } catch {
      // 单帧解析失败不该中断整轮对话：跳过，继续读下一帧
      return null
    }
  }
  return null
}

/** 把任意 SSE 响应拆成事件流。`/agent` 与 `/agent/resume` 共用。 */
export async function* readSse(
  response: Response,
): AsyncGenerator<AgentEvent> {
  if (!response.body) {
    throw new ApiError('响应没有可读流（浏览器环境异常）')
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })

      let boundary = buffer.indexOf('\n\n')
      while (boundary >= 0) {
        const raw = buffer.slice(0, boundary)
        buffer = buffer.slice(boundary + 2)
        const event = parseFrame(raw)
        if (event) yield event
        boundary = buffer.indexOf('\n\n')
      }
    }
  } finally {
    reader.releaseLock()
  }
}

/** 发 POST 并断言是 SSE 响应；错误体尽量解析成人话。 */
export async function postSse(
  path: string,
  body: unknown,
  signal?: AbortSignal,
): Promise<Response> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    method: 'POST',
    headers: {
      Accept: 'text/event-stream',
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(body),
    signal,
  })

  if (!response.ok) {
    let detail = `HTTP ${response.status}`
    try {
      const payload = (await response.json()) as { detail?: unknown }
      if (payload?.detail) detail = JSON.stringify(payload.detail)
    } catch {
      // 忽略：错误体不是 JSON 时保留状态码即可
    }
    throw new ApiError(`请求失败：${detail}`, response.status)
  }
  return response
}

export async function* streamChat(
  request: ChatRequest,
  signal?: AbortSignal,
): AsyncGenerator<AgentEvent> {
  const response = await postSse('/agent', request, signal)
  yield* readSse(response)
}

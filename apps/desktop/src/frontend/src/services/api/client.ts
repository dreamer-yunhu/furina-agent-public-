// ── AI-ASSISTED ── 本文件由 AI 生成，待人工复核 ──
// 复核重点：
//   1. 超时是**必须**的：本地服务没起来时 fetch 会挂很久，不设超时界面会一直转圈。
//   2. 错误一律转成 ApiError 并带人话消息；不要把原生 TypeError 直接抛给 UI。
//   3. 不在这里做重试。重试会让"未连接"的判断变得不确定，交给调用方决定。
//
// 为什么超时只给 4 秒：桌面版本地回环，正常响应在毫秒级；
// 超过 4 秒基本可以判定为"服务没起来"或"进程卡住"。

import { API_BASE_URL } from './config'
import type { ApiHealth } from './types'

export const DEFAULT_TIMEOUT_MS = 4000

export class ApiError extends Error {
  readonly status?: number

  constructor(message: string, status?: number) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

interface FetchOptions extends RequestInit {
  timeoutMs?: number
}

export async function apiFetch<T>(
  path: string,
  { timeoutMs = DEFAULT_TIMEOUT_MS, ...init }: FetchOptions = {},
): Promise<T> {
  if (typeof fetch !== 'function') {
    throw new ApiError('当前运行环境没有 fetch')
  }

  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeoutMs)

  try {
    const response = await fetch(`${API_BASE_URL}${path}`, {
      ...init,
      signal: controller.signal,
      headers: {
        Accept: 'application/json',
        ...(init.body ? { 'Content-Type': 'application/json' } : {}),
        ...init.headers,
      },
    })

    if (!response.ok) {
      throw new ApiError(
        `请求失败：HTTP ${response.status} ${response.statusText}`,
        response.status,
      )
    }

    return (await response.json()) as T
  } catch (error) {
    if (error instanceof ApiError) throw error
    if (error instanceof Error && error.name === 'AbortError') {
      throw new ApiError(`请求超时（${timeoutMs}ms）`)
    }
    throw new ApiError(
      `无法连接本地服务 ${API_BASE_URL}：${
        error instanceof Error ? error.message : String(error)
      }`,
    )
  } finally {
    clearTimeout(timer)
  }
}

/** 健康检查。只有 status === 'ok' 才算连上。 */
export async function getHealth(): Promise<ApiHealth> {
  return apiFetch<ApiHealth>('/healthz', { timeoutMs: 2500 })
}

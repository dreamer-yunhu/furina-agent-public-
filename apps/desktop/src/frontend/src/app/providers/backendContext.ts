// ── AI-ASSISTED ── 本文件由 AI 生成，待人工复核 ──
// 复核重点：context 与 Provider 分文件是仓库既有约定（见 themeContext.ts），
// 不要把它们合并 —— react-refresh 对同一文件里「组件 + 非组件导出」会失效。

import { createContext, useContext } from 'react'

import type { ApiThreadSummary } from '../../services/api/types'

/**
 * checking：正在探测；online：/healthz 通过且线程列表已取到；
 * offline：探测失败（服务没起 / 超时 / 返回非 ok）。
 */
export type BackendStatus = 'checking' | 'online' | 'offline'

export interface BackendState {
  status: BackendStatus
  /** offline 时给 UI 一个可读的原因，不要吞掉 */
  error?: string
  threads: ApiThreadSummary[]
  reload: () => void
}

export const BackendContext = createContext<BackendState | null>(null)

export function useBackend(): BackendState {
  const value = useContext(BackendContext)
  if (!value) {
    throw new Error('useBackend 必须在 BackendProvider 内使用')
  }
  return value
}

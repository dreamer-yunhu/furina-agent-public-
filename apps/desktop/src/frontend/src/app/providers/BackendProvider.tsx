// ── AI-ASSISTED ── 本文件由 AI 生成，待人工复核 ──
// 复核重点：
//   1. **不静默失败**：offline 时把原因写进 state，UI 必须显示出来。
//   2. 探测顺序是先 /healthz 再取列表 —— 服务半启动时列表会 500，
//      先探活能把"没起来"和"起来了但坏了"区分开。
//   3. import.meta.env.MODE === 'test' 直接跳过：jsdom 里发真实请求会拖慢用例，
//      且结果取决于本机有没有起后端。测试要覆盖这条路径应当 mock，而不是靠环境。

import {
  useCallback,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'

import { getHealth } from '../../services/api/client'
import { listThreads } from '../../services/api/threads'
import type { ApiThreadSummary } from '../../services/api/types'
import {
  BackendContext,
  type BackendState,
  type BackendStatus,
} from './backendContext'

const THREAD_PAGE_SIZE = 20
/** 在线时多久探一次存活；够快发现崩溃，又不至于刷日志 */
const ONLINE_HEALTH_INTERVAL_MS = 10_000

const IS_TEST = import.meta.env.MODE === 'test'
const TEST_SKIP_REASON = '测试环境跳过后端探测'

export function BackendProvider({ children }: { children: ReactNode }) {
  // 初始状态在 useState 里定，不在 effect 里 setState —— 避免多一轮渲染，
  // 也满足 react(set-state-in-effect) 规则。
  const [status, setStatus] = useState<BackendStatus>(
    IS_TEST ? 'offline' : 'checking',
  )
  const [threads, setThreads] = useState<ApiThreadSummary[]>([])
  const [error, setError] = useState<string | undefined>(
    IS_TEST ? TEST_SKIP_REASON : undefined,
  )
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    if (IS_TEST) return

    let cancelled = false

    void (async () => {
      try {
        const health = await getHealth()
        if (cancelled) return
        if (health.status !== 'ok') {
          throw new Error(`健康检查未通过：${health.status}`)
        }

        const list = await listThreads(1, THREAD_PAGE_SIZE)
        if (cancelled) return

        setThreads(list.items)
        setStatus('online')
      } catch (e) {
        if (cancelled) return
        setThreads([])
        setStatus('offline')
        setError(e instanceof Error ? e.message : String(e))
      }
    })()

    return () => {
      cancelled = true
    }
  }, [attempt])

  const reload = useCallback(() => {
    if (IS_TEST) return
    // 重试时先把状态拨回 checking，让 UI 知道正在重新探测
    setStatus('checking')
    setError(undefined)
    setAttempt((n) => n + 1)
  }, [])

  // 在线期间的存活检查。
  // 没有它的话，"已连接"是启动那一刻的结论，后端中途崩了顶栏仍然显示已连接 ——
  // 一个只会变绿不会变红的指示灯比没有更糟。只探 /healthz，不重拉列表，
  // 避免把用户正在看的线程状态刷掉。
  useEffect(() => {
    if (IS_TEST || status !== 'online') return

    const timer = setInterval(() => {
      void (async () => {
        try {
          const health = await getHealth()
          if (health.status !== 'ok') throw new Error(`健康检查未通过：${health.status}`)
        } catch (e) {
          setStatus('offline')
          setError(e instanceof Error ? e.message : String(e))
        }
      })()
    }, ONLINE_HEALTH_INTERVAL_MS)

    return () => clearInterval(timer)
  }, [status])

  // 离线自动重试。
  // 背景：应用启动早于后端时（或后端中途崩了），原来只探一次就永远停在"未连接"，
  // 用户只能重启应用。这里每 5 秒重探一次；连上后 effect 自动停。
  // 注意调的是 reload（会把状态拨回 checking），否则 status 一直是 offline、
  // 值没变化，React 不会重新触发本 effect，重试就只会发生一次。
  useEffect(() => {
    if (IS_TEST || status !== 'offline') return
    const timer = setTimeout(() => reload(), 5000)
    return () => clearTimeout(timer)
  }, [status, reload])

  const value = useMemo<BackendState>(
    () => ({ status, error, threads, reload }),
    [status, error, threads, reload],
  )

  return (
    <BackendContext.Provider value={value}>{children}</BackendContext.Provider>
  )
}

// ── AI-ASSISTED ── 本文件由 AI 生成，待人工复核 ──
// 复核重点：
//   1. 用 hash 路由而不是 history 路由 —— Tauri 生产环境从 dist 加载，
//      不保证对未知路径回退 index.html；hash 在 WebView 与浏览器里都稳定。
//   2. 这里只做「路径 → 路由名 + 参数」的纯函数匹配，不引入路由库。
//      将来需要嵌套路由/loader 时再替换成 react-router，页面组件不需要改。
//   3. `navigate` 同时监听 hashchange 与 popstate，保证前进/后退可用。

import { useEffect, useState } from 'react'

export type RouteName =
  | 'chat'
  | 'tasks'
  | 'task-detail'
  | 'execution-detail'
  | 'approvals'
  | 'approval-detail'
  | 'audit'
  | 'audit-thread'
  | 'audit-detail'
  | 'settings'
  | 'not-found'

export interface RouteMatch {
  name: RouteName
  params: Record<string, string>
  path: string
}

interface RoutePattern {
  name: RouteName
  segments: string[]
}

const ROUTES: RoutePattern[] = [
  { name: 'chat', segments: ['chat'] },
  { name: 'chat', segments: ['chat', ':threadId'] },
  { name: 'tasks', segments: ['tasks'] },
  { name: 'task-detail', segments: ['tasks', ':taskId'] },
  {
    name: 'execution-detail',
    segments: ['tasks', ':taskId', 'executions', ':executionId'],
  },
  { name: 'approvals', segments: ['approvals'] },
  { name: 'approval-detail', segments: ['approvals', ':approvalRequestId'] },
  { name: 'audit', segments: ['audit'] },
  { name: 'audit-thread', segments: ['audit', ':threadId'] },
  { name: 'audit-detail', segments: ['audit', ':threadId', ':approvalId'] },
  { name: 'settings', segments: ['settings'] },
]

export const ROUTE_TITLES: Record<RouteName, string> = {
  chat: '对话',
  tasks: '任务',
  'task-detail': '任务详情',
  'execution-detail': '执行详情',
  approvals: '审批',
  'approval-detail': '审批详情',
  audit: '审计',
  'audit-thread': '线程审计',
  'audit-detail': '审批记录',
  settings: '设置',
  'not-found': '页面不存在',
}

function splitPath(path: string): string[] {
  const clean = path.split('?')[0]?.split('#')[0] ?? ''
  return clean
    .split('/')
    .filter(Boolean)
    .map((segment) => {
      try {
        return decodeURIComponent(segment)
      } catch {
        return segment
      }
    })
}

export function matchPath(path: string): RouteMatch {
  const segments = splitPath(path)
  if (segments.length === 0) {
    return { name: 'chat', params: {}, path: '/chat' }
  }

  for (const route of ROUTES) {
    if (route.segments.length !== segments.length) continue

    const params: Record<string, string> = {}
    let matched = true

    for (let index = 0; index < route.segments.length; index += 1) {
      const pattern = route.segments[index]
      const value = segments[index]

      if (pattern.startsWith(':')) {
        params[pattern.slice(1)] = value
      } else if (pattern !== value) {
        matched = false
        break
      }
    }

    if (matched) {
      return { name: route.name, params, path: `/${segments.join('/')}` }
    }
  }

  return { name: 'not-found', params: {}, path: `/${segments.join('/')}` }
}

function readLocation(): string {
  const raw = window.location.hash.replace(/^#/, '')
  return raw || '/'
}

export function useHashLocation(): string {
  const [location, setLocation] = useState<string>(readLocation)

  useEffect(() => {
    const sync = () => setLocation(readLocation())
    window.addEventListener('hashchange', sync)
    window.addEventListener('popstate', sync)
    return () => {
      window.removeEventListener('hashchange', sync)
      window.removeEventListener('popstate', sync)
    }
  }, [])

  return location
}

export function navigate(to: string, options: { replace?: boolean } = {}): void {
  const target = to.startsWith('/') ? to : `/${to}`
  const hash = `#${target}`

  if (options.replace) {
    const url = `${window.location.pathname}${window.location.search}${hash}`
    window.history.replaceState(null, '', url)
  } else if (window.location.hash !== hash) {
    window.history.pushState(null, '', hash)
  }

  // jsdom 不会在 pushState/replaceState 后自动派发 hashchange；显式同步一次。
  window.dispatchEvent(new Event('hashchange'))
}

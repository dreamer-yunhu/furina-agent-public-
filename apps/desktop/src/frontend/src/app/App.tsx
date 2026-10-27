// ── AI-ASSISTED ── 本文件由 AI 生成，待人工复核 ──
// 复核重点：
//   1. 路由 → 页面的映射集中在这里；新增页面只改这一处与 router.ts。
//   2. 不在 App 里发请求、不推断任务状态。
//   3. 侧栏折叠、详情面板开关、主题切换是纯 UI 状态，刷新后重置（主题除外）。

import { useEffect, useMemo, useState } from 'react'

import { artwork } from '../assets/app/artwork'
import { AppBackground } from '../components/placeholders/AppBackground'
import { CharacterPlaceholder } from '../components/placeholders/CharacterPlaceholder'
import { RouteInspector } from '../features/inspector/RouteInspector'
import { HeaderBar } from '../features/navigation/HeaderBar'
import { SidebarNav } from '../features/navigation/SidebarNav'
import { WorkbenchLayout } from '../layouts/WorkbenchLayout'
import { ApprovalDetailPage } from '../pages/ApprovalDetailPage'
import { ApprovalsPage } from '../pages/ApprovalsPage'
import { AuditApprovalDetailPage } from '../pages/AuditApprovalDetailPage'
import { AuditPage } from '../pages/AuditPage'
import { AuditThreadPage } from '../pages/AuditThreadPage'
import { ChatPage } from '../pages/ChatPage'
import { ExecutionDetailPage } from '../pages/ExecutionDetailPage'
import { NotFoundPage } from '../pages/NotFoundPage'
import { SettingsPage } from '../pages/SettingsPage'
import { TaskDetailPage } from '../pages/TaskDetailPage'
import { TasksPage } from '../pages/TasksPage'
import { ThemeProvider } from './providers/ThemeProvider'
import { useThemeContext } from './providers/themeContext'
import { matchPath, navigate, ROUTE_TITLES, useHashLocation } from './router'
import type { RouteMatch } from './router'

function renderPage(match: RouteMatch) {
  switch (match.name) {
    case 'chat':
      return (
        <ChatPage
          key={match.params.threadId ?? 'new-chat'}
          threadId={match.params.threadId}
        />
      )
    case 'tasks':
      return <TasksPage />
    case 'task-detail':
      return <TaskDetailPage taskId={match.params.taskId} />
    case 'execution-detail':
      return (
        <ExecutionDetailPage
          taskId={match.params.taskId}
          executionId={match.params.executionId}
        />
      )
    case 'approvals':
      return <ApprovalsPage />
    case 'approval-detail':
      return (
        <ApprovalDetailPage
          approvalRequestId={match.params.approvalRequestId}
        />
      )
    case 'audit':
      return <AuditPage />
    case 'audit-thread':
      return <AuditThreadPage threadId={match.params.threadId} />
    case 'audit-detail':
      return (
        <AuditApprovalDetailPage
          threadId={match.params.threadId}
          approvalId={match.params.approvalId}
        />
      )
    case 'settings':
      return <SettingsPage />
    default:
      return <NotFoundPage />
  }
}

const INSPECTOR_AVAILABLE: RouteMatch['name'][] = [
  'chat',
  'task-detail',
  'execution-detail',
  'approval-detail',
  'audit-thread',
  'audit-detail',
]

const INSPECTOR_DEFAULT_OPEN: RouteMatch['name'][] = [
  'task-detail',
  'execution-detail',
  'approval-detail',
  'audit-thread',
  'audit-detail',
]

function AppShell() {
  const location = useHashLocation()
  const match = useMemo(() => matchPath(location), [location])
  const { mode: themeMode, cycle: cycleTheme } = useThemeContext()
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)
  // 面板开关按路由路径记录：换路由时 path 不匹配，自动回到该路由的默认值，
  // 不需要在 effect 里 setState（也避免多一次渲染）。
  const [inspectorState, setInspectorState] = useState<{
    path: string
    open: boolean
  } | null>(null)

  useEffect(() => {
    const rawHash = window.location.hash.replace(/^#/, '')
    if (rawHash === '' || rawHash === '/') {
      navigate('/chat', { replace: true })
    }
  }, [])

  const inspectorAvailable = INSPECTOR_AVAILABLE.includes(match.name)
  const inspectorOpen =
    inspectorState?.path === match.path
      ? inspectorState.open
      : INSPECTOR_DEFAULT_OPEN.includes(match.name)
  const toggleInspector = () =>
    setInspectorState({ path: match.path, open: !inspectorOpen })
  const activeThreadId =
    match.name === 'chat' ? match.params.threadId : undefined

  return (
    <WorkbenchLayout
      header={
        <HeaderBar
          title={ROUTE_TITLES[match.name]}
          sidebarCollapsed={sidebarCollapsed}
          onToggleSidebar={() => setSidebarCollapsed((current) => !current)}
          inspectorAvailable={inspectorAvailable}
          inspectorOpen={inspectorOpen}
          onToggleInspector={toggleInspector}
          themeMode={themeMode}
          onCycleTheme={cycleTheme}
        />
      }
      sidebar={
        <SidebarNav
          active={match.name}
          collapsed={sidebarCollapsed}
          activeThreadId={activeThreadId}
        />
      }
      inspector={inspectorAvailable ? <RouteInspector match={match} /> : undefined}
      inspectorOpen={inspectorAvailable && inspectorOpen}
      onCloseInspector={() =>
        setInspectorState({ path: match.path, open: false })
      }
      sidebarCollapsed={sidebarCollapsed}
      mainMode={match.name === 'chat' ? 'fixed' : 'scroll'}
      background={<AppBackground src={artwork.background} />}
      character={<CharacterPlaceholder src={artwork.character} />}
    >
      {renderPage(match)}
    </WorkbenchLayout>
  )
}

export function App() {
  return (
    <ThemeProvider>
      <AppShell />
    </ThemeProvider>
  )
}

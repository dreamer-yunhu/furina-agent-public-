// ── AI-ASSISTED ── 本文件由 AI 生成，待人工复核 ──
// 复核重点：
//   1. 路由 → 页面的映射集中在这里；新增页面只改这一处与 router.ts。
//   2. 不在 App 里发请求、不推断任务状态。
//   3. Inspector 的显隐由路由决定，页面组件不直接操作布局。

import { useEffect, useMemo } from 'react'

import { artwork } from '../assets/app/artwork'
import { AppBackground } from '../components/placeholders/AppBackground'
import { CharacterPlaceholder } from '../components/placeholders/CharacterPlaceholder'
import { RouteInspector } from '../features/inspector/RouteInspector'
import { HeaderBar } from '../features/navigation/HeaderBar'
import { SidebarNav } from '../features/navigation/SidebarNav'
import { WorkbenchLayout } from '../layouts/WorkbenchLayout'
import { ApprovalDetailPage } from '../pages/ApprovalDetailPage'
import { ApprovalsPage } from '../pages/ApprovalsPage'
import { ChatPage } from '../pages/ChatPage'
import { ExecutionDetailPage } from '../pages/ExecutionDetailPage'
import { NotFoundPage } from '../pages/NotFoundPage'
import { SettingsPage } from '../pages/SettingsPage'
import { TaskDetailPage } from '../pages/TaskDetailPage'
import { TasksPage } from '../pages/TasksPage'
import { resolveWindowRole } from '../services/desktop/windowRoles'
import { matchPath, navigate, ROUTE_TITLES, useHashLocation } from './router'
import type { RouteMatch } from './router'

function renderPage(match: RouteMatch) {
  switch (match.name) {
    case 'chat':
      return <ChatPage threadId={match.params.threadId} />
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
      return <ApprovalDetailPage approvalRequestId={match.params.approvalRequestId} />
    case 'settings':
      return <SettingsPage />
    default:
      return <NotFoundPage />
  }
}

export function App() {
  const location = useHashLocation()
  const match = useMemo(() => matchPath(location), [location])
  const windowRole = resolveWindowRole()
  const showInspector =
    match.name === 'task-detail' ||
    match.name === 'execution-detail' ||
    match.name === 'approval-detail'

  // 只在首次挂载时补默认路由，且以**当前 hash** 为准：
  // 避免「加载时无 hash → 用户/外部已切到 #/tasks → 旧 effect 又把它改回 #/chat」的竞态。
  useEffect(() => {
    const rawHash = window.location.hash.replace(/^#/, '')
    if (rawHash === '' || rawHash === '/') {
      navigate('/chat', { replace: true })
    }
  }, [])

  return (
    <WorkbenchLayout
      header={<HeaderBar title={ROUTE_TITLES[match.name]} windowRole={windowRole} />}
      sidebar={<SidebarNav active={match.name} />}
      inspector={showInspector ? <RouteInspector match={match} /> : undefined}
      inspectorOpen={showInspector}
      background={<AppBackground src={artwork.background} />}
      character={<CharacterPlaceholder src={artwork.character} />}
    >
      {renderPage(match)}
    </WorkbenchLayout>
  )
}

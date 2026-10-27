// ── AI-ASSISTED ── 本文件由 AI 生成，待人工复核 ──
// 复核重点：导航项只描述「去哪里」，不读取任务/审批状态。

import { Link } from '../../app/Link'
import type { RouteName } from '../../app/router'

interface NavItem {
  to: string
  label: string
  caption: string
  matches: RouteName[]
}

const NAV_ITEMS: NavItem[] = [
  { to: '/chat', label: '对话', caption: 'Chat', matches: ['chat'] },
  {
    to: '/tasks',
    label: '任务',
    caption: 'Tasks',
    matches: ['tasks', 'task-detail', 'execution-detail'],
  },
  {
    to: '/approvals',
    label: '审批',
    caption: 'Approvals',
    matches: ['approvals', 'approval-detail'],
  },
  { to: '/settings', label: '设置', caption: 'Settings', matches: ['settings'] },
]

interface SidebarNavProps {
  active: RouteName
}

export function SidebarNav({ active }: SidebarNavProps) {
  return (
    <div className="sidebar-nav">
      <nav className="sidebar-nav__list" aria-label="主导航">
        {NAV_ITEMS.map((item) => {
          const isActive = item.matches.includes(active)
          return (
            <Link
              key={item.to}
              to={item.to}
              className="sidebar-nav__item"
              aria-current={isActive ? 'page' : undefined}
            >
              <span className="sidebar-nav__label">{item.label}</span>
              <span className="sidebar-nav__caption">{item.caption}</span>
            </Link>
          )
        })}
      </nav>
      <div className="sidebar-nav__footer">
        <span className="tag tag--placeholder">F1</span>
        <p>骨架阶段：未接入真实后端数据。</p>
      </div>
    </div>
  )
}

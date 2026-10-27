// ── AI-ASSISTED ── 本文件由 AI 生成，待人工复核 ──
// 复核重点：
//   1. 结构对齐 Codex 原型：品牌 → 新建会话 → 工作区导航 → 最近会话 → 底部用户。
//   2. 折叠态由 CSS 的 data-sidebar 控制；这里只提供 title 与导航语义。
//   3. 所有线程/计数来自 demo/data.ts，不代表真实后端。

import { Link } from '../../app/Link'
import type { RouteName } from '../../app/router'
import { artwork } from '../../assets/app/artwork'
import { Icon } from '../../components/ui/Icon'
import { demoApprovals, demoTasks, demoThreads } from '../../demo/data'

const DOT_CLASS: Record<string, string> = {
  waiting_approval: '',
  completed: 'green',
  failed: 'red',
  idle: 'gray',
}

interface SidebarNavProps {
  active: RouteName
  collapsed: boolean
  activeThreadId?: string
}

export function SidebarNav({
  active,
  collapsed,
  activeThreadId,
}: SidebarNavProps) {
  const pendingAudit = demoApprovals.filter(
    (approval) => approval.status === 'pending',
  ).length
  const isChat = active === 'chat'
  const newChatActive = isChat && !activeThreadId

  return (
    <div className="sidebar">
      <div className="brand">
        <div className="logo" aria-hidden="true">
          {artwork.logo ? (
            <img className="logo__image" src={artwork.logo} alt="" />
          ) : (
            '✦'
          )}
        </div>
        <div className="brand-text">
          芙芙 Agent
          <small>PERSONAL WORKSPACE</small>
        </div>
      </div>

      <Link
        to="/chat"
        className="new-chat"
        aria-current={newChatActive ? 'page' : undefined}
        title="新建会话"
      >
        <span aria-hidden="true">＋</span>
        <span className="new-label">新建会话</span>
      </Link>

      <div className="nav-label">工作区</div>
      <nav className="nav-list" aria-label="主导航">
        <Link
          to="/chat"
          className={isChat ? 'nav-item active' : 'nav-item'}
          aria-current={isChat ? 'page' : undefined}
          title="会话"
        >
          <span className="ico">
            <Icon name="message" size={15} />
          </span>
          <span>会话</span>
        </Link>
        <Link
          to="/tasks"
          className={
            ['tasks', 'task-detail', 'execution-detail'].includes(active)
              ? 'nav-item active'
              : 'nav-item'
          }
          aria-current={
            ['tasks', 'task-detail', 'execution-detail'].includes(active)
              ? 'page'
              : undefined
          }
          title="任务"
        >
          <span className="ico">
            <Icon name="list" size={15} />
          </span>
          <span>任务</span>
          <span className="count">{demoTasks.length}</span>
        </Link>
        <Link
          to="/audit"
          className={
            ['audit', 'audit-thread', 'audit-detail'].includes(active)
              ? 'nav-item active'
              : 'nav-item'
          }
          aria-current={
            ['audit', 'audit-thread', 'audit-detail'].includes(active)
              ? 'page'
              : undefined
          }
          title="审计"
        >
          <span className="ico">
            <Icon name="shield" size={15} />
          </span>
          <span>审计</span>
          <span className="count">{pendingAudit}</span>
        </Link>
        <Link
          to="/settings"
          className={active === 'settings' ? 'nav-item active' : 'nav-item'}
          aria-current={active === 'settings' ? 'page' : undefined}
          title="设置"
        >
          <span className="ico">
            <Icon name="sliders" size={15} />
          </span>
          <span>设置</span>
        </Link>
      </nav>

      <div className="side-section">
        <div className="nav-label">最近会话</div>
        {demoThreads.map((thread) => (
          <Link
            key={thread.id}
            to={`/chat/${thread.id}`}
            className={
              thread.id === activeThreadId ? 'thread active' : 'thread'
            }
            aria-current={thread.id === activeThreadId ? 'page' : undefined}
            title={collapsed ? thread.title : undefined}
          >
            <div className="thread-title">{thread.title}</div>
            <div className="thread-meta">
              <span
                className={`dot ${DOT_CLASS[thread.status] ?? ''}`}
                aria-hidden="true"
              />
              {thread.updatedAt}
              {thread.pendingApprovals
                ? ` · ${thread.pendingApprovals} 待审批`
                : ''}
            </div>
          </Link>
        ))}
      </div>

      <div className="sidebar-bottom">
        <div className="profile">
          <div className="avatar">
            {artwork.avatar ? (
              <img className="avatar__image" src={artwork.avatar} alt="" />
            ) : (
              '芙'
            )}
          </div>
          <div>
            芙芙 Agent
            <small>本地工作空间 · Demo</small>
          </div>
        </div>
      </div>
    </div>
  )
}

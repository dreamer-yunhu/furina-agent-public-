// ── AI-ASSISTED ── 本文件由 AI 生成，待人工复核 ──
// 复核重点：
//   1. 结构对齐 Codex 原型：品牌 → 新建会话 → 工作区导航 → 最近会话 → 底部用户。
//   2. 折叠态由 CSS 的 data-sidebar 控制；这里只提供 title 与导航语义。
//   3. 所有线程/计数来自 demo/data.ts，不代表真实后端。

import { useState } from 'react'

import { Link } from '../../app/Link'
import { useBackend } from '../../app/providers/backendContext'
import { navigate, type RouteName } from '../../app/router'
import { artwork } from '../../assets/app/artwork'
import { Icon } from '../../components/ui/Icon'
import { demoApprovals, demoTasks, demoThreads } from '../../demo/data'
import {
  createThread,
  deleteThread,
  renameThread,
} from '../../services/api/threads'
import type { ApiThreadSummary } from '../../services/api/types'

const DOT_CLASS: Record<string, string> = {
  waiting_approval: '',
  completed: 'green',
  failed: 'red',
  idle: 'gray',
}

/** 最近会话的展示模型：Demo 与真实数据在这里归一，渲染层只认这些字段。 */
interface RecentThreadItem {
  id: string
  title: string
  meta: string
  /** 真实列表接口不返回运行状态，所以允许缺失 —— 缺失时不要画状态点 */
  status?: string
  pendingApprovals?: number
}

/**
 * 后端返回的是无时区的本地时间字符串（如 2026-10-26T14:20:32.867297），
 * 直接 new Date() 会按本地时区解析，正好符合预期。
 */
function formatThreadTime(iso: string): string {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return iso

  const now = new Date()
  const yesterday = new Date(now)
  yesterday.setDate(now.getDate() - 1)

  const hhmm = `${String(date.getHours()).padStart(2, '0')}:${String(
    date.getMinutes(),
  ).padStart(2, '0')}`

  if (date.toDateString() === now.toDateString()) return `今天 ${hhmm}`
  if (date.toDateString() === yesterday.toDateString()) return `昨天 ${hhmm}`
  return `${date.getMonth() + 1}月${date.getDate()}日`
}

interface SidebarNavProps {
  active: RouteName
  collapsed: boolean
  activeThreadId?: string
  /** 后端是否已连上；未连上时回落到 Demo 数据 */
  backendOnline?: boolean
  backendThreads?: ApiThreadSummary[]
}

export function SidebarNav({
  active,
  collapsed,
  activeThreadId,
  backendOnline = false,
  backendThreads = [],
}: SidebarNavProps) {
  const backend = useBackend()
  const [editingId, setEditingId] = useState<string | null>(null)
  const [draftTitle, setDraftTitle] = useState('')
  const [actionError, setActionError] = useState<string | undefined>(undefined)

  const pendingAudit = demoApprovals.filter(
    (approval) => approval.status === 'pending',
  ).length
  const isChat = active === 'chat'
  const newChatActive = isChat && !activeThreadId

  /** 在线时真建线程；离线时退回 Demo 的空会话页 */
  const handleNewChat = async () => {
    if (!backendOnline) {
      navigate('/chat')
      return
    }
    setActionError(undefined)
    try {
      const stamp = new Date().toLocaleString('zh-CN', {
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
      })
      const created = await createThread(`新会话 ${stamp}`)
      backend.reload()
      navigate(`/chat/${created.id}`)
    } catch (error) {
      setActionError(error instanceof Error ? error.message : String(error))
    }
  }

  const startRename = (id: string, title: string) => {
    setEditingId(id)
    setDraftTitle(title)
  }

  const commitRename = async () => {
    if (!editingId) return
    const title = draftTitle.trim()
    const id = editingId
    setEditingId(null)
    if (!title) return
    try {
      await renameThread(id, title)
      backend.reload()
    } catch (error) {
      setActionError(error instanceof Error ? error.message : String(error))
    }
  }

  const handleDelete = async (id: string, title: string) => {
    // 删除会连带删掉 checkpoint 里的聊天记录，必须二次确认
    if (!window.confirm(`删除会话「${title}」？聊天记录会一并删除，且不可恢复。`)) {
      return
    }
    try {
      await deleteThread(id)
      backend.reload()
      if (id === activeThreadId) navigate('/chat')
    } catch (error) {
      setActionError(error instanceof Error ? error.message : String(error))
    }
  }

  const useRealThreads = backendOnline && backendThreads.length > 0
  const recentThreads: RecentThreadItem[] = useRealThreads
    ? backendThreads.map((thread) => ({
        id: thread.id,
        title: thread.title,
        meta: formatThreadTime(thread.updated_at),
      }))
    : demoThreads.map((thread) => ({
        id: thread.id,
        title: thread.title,
        meta: thread.updatedAt,
        status: thread.status,
        pendingApprovals: thread.pendingApprovals,
      }))

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

      <button
        type="button"
        className="new-chat"
        aria-current={newChatActive ? 'page' : undefined}
        title={backendOnline ? '新建会话（会写入后端）' : '新建会话（未连接，仅前端）'}
        onClick={() => void handleNewChat()}
      >
        <span aria-hidden="true">＋</span>
        <span className="new-label">新建会话</span>
      </button>

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
        {recentThreads.map((thread) =>
          editingId === thread.id ? (
            <div className="thread thread--editing" key={thread.id}>
              <input
                className="thread-rename"
                value={draftTitle}
                autoFocus
                maxLength={255}
                aria-label="重命名会话"
                onChange={(event) => setDraftTitle(event.target.value)}
                onBlur={() => void commitRename()}
                onKeyDown={(event) => {
                  if (event.key === 'Enter') void commitRename()
                  if (event.key === 'Escape') setEditingId(null)
                }}
              />
            </div>
          ) : (
            <div className="thread-row" key={thread.id}>
              <Link
                to={`/chat/${thread.id}`}
                className={
                  thread.id === activeThreadId ? 'thread active' : 'thread'
                }
                aria-current={thread.id === activeThreadId ? 'page' : undefined}
                title={collapsed ? thread.title : undefined}
              >
                <div className="thread-title">{thread.title}</div>
                <div className="thread-meta">
                  {thread.status ? (
                    <span
                      className={`dot ${DOT_CLASS[thread.status] ?? ''}`}
                      aria-hidden="true"
                    />
                  ) : null}
                  {thread.meta}
                  {thread.pendingApprovals
                    ? ` · ${thread.pendingApprovals} 待审批`
                    : ''}
                </div>
              </Link>

              {useRealThreads ? (
                <div className="thread-actions">
                  <button
                    type="button"
                    title="重命名"
                    aria-label={`重命名 ${thread.title}`}
                    onClick={(event) => {
                      event.preventDefault()
                      startRename(thread.id, thread.title)
                    }}
                  >
                    ✎
                  </button>
                  <button
                    type="button"
                    title="删除会话"
                    aria-label={`删除 ${thread.title}`}
                    onClick={(event) => {
                      event.preventDefault()
                      void handleDelete(thread.id, thread.title)
                    }}
                  >
                    ✕
                  </button>
                </div>
              ) : null}
            </div>
          ),
        )}

        {actionError ? (
          <div className="thread-error" role="alert">
            {actionError}
          </div>
        ) : null}
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
            <small>
              {backendOnline ? '本地工作空间 · 已连接' : '本地工作空间 · Demo'}
            </small>
          </div>
        </div>
      </div>
    </div>
  )
}

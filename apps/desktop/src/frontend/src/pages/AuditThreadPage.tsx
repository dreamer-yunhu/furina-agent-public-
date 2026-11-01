// ── AI-ASSISTED ── 本文件由 AI 生成/改写，待人工复核 ──
// 复核重点：
//   1. ★ 从 demo 改成真实接口：线程标题走 `GET /agent/threads`（按 id 找），
//      任务走 `GET /agent/tasks?thread_id=`，审批走 `GET /agent/approvals?thread_id=`。
//   2. 后端没有"线程详情"接口，标题只能从列表里捞；捞不到就显示短 id，
//      不编造标题。
//   3. 任务与审批**分别渲染**：一个任务可能没有审批，一条审批也未必属于当前页的任务。

import { useEffect, useState } from 'react'

import { Link } from '../app/Link'
import { ContentSection } from '../components/ui/ContentSection'
import { EmptyState } from '../components/ui/EmptyState'
import { PageHeader } from '../components/ui/PageHeader'
import { StatusPill } from '../components/ui/StatusPill'
import {
  APPROVAL_STATUS_META,
  TASK_STATUS_META,
  TOOL_EXECUTION_META,
  statusMeta,
} from '../features/shared/statusMeta'
import { ApiError } from '../services/api/client'
import {
  listApprovals,
  listTasks,
  type ApiApprovalItem,
  type ApiTaskItem,
} from '../services/api/activity'
import { listThreads } from '../services/api/threads'

interface Data {
  title: string
  tasks: ApiTaskItem[]
  approvals: ApiApprovalItem[]
}

type LoadState =
  | { kind: 'loading' }
  | { kind: 'error'; message: string }
  | { kind: 'ready'; data: Data }

function formatTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return iso
  return date.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

export function AuditThreadPage({ threadId }: { threadId: string }) {
  const [state, setState] = useState<LoadState>({ kind: 'loading' })

  useEffect(() => {
    let cancelled = false
    setState({ kind: 'loading' })

    Promise.all([
      listTasks(1, 100, threadId),
      listApprovals({ threadId, size: 100 }),
      listThreads(1, 100),
    ])
      .then(([tasks, approvals, threads]) => {
        if (cancelled) return
        const title =
          threads.items.find((item) => item.id === threadId)?.title ??
          tasks.items[0]?.thread_title ??
          threadId
        setState({
          kind: 'ready',
          data: { title, tasks: tasks.items, approvals: approvals.items },
        })
      })
      .catch((error: unknown) => {
        if (cancelled) return
        setState({
          kind: 'error',
          message:
            error instanceof ApiError || error instanceof Error
              ? error.message
              : String(error),
        })
      })

    return () => {
      cancelled = true
    }
  }, [threadId])

  if (state.kind === 'loading') {
    return (
      <div className="page">
        <PageHeader title="线程审计" description="正在从本地服务读取…" />
        <div className="page-content">
          <EmptyState title="加载中" description={`thread_id = ${threadId}`} />
        </div>
      </div>
    )
  }

  if (state.kind === 'error') {
    return (
      <div className="page">
        <PageHeader title="读取失败" description="本地服务没有返回可用数据。" />
        <div className="page-content">
          <EmptyState title="请求失败" description={state.message} />
          <div className="page__actions">
            <Link className="pill-btn" to="/audit">
              返回审计
            </Link>
          </div>
        </div>
      </div>
    )
  }

  const { title, tasks, approvals } = state.data

  return (
    <div className="page">
      <PageHeader
        title={title}
        description={`线程 ${threadId}`}
        meta={
          <>
            <span className="tag">{tasks.length} 个任务</span>
            <span className="tag">{approvals.length} 条审批</span>
            <Link className="pill-btn" to={`/chat/${threadId}`}>
              进入会话 ↗
            </Link>
          </>
        }
      />

      <div className="page-content">
        <ContentSection title="任务">
          {tasks.length ? (
            tasks.map((task) => {
              const meta = statusMeta(TASK_STATUS_META, task.status)
              return (
                <Link key={task.id} className="record" to={`/tasks/${task.id}`}>
                  <div>
                    <b>{task.instruction || '(无指令)'}</b>
                    <small>
                      {formatTime(task.created_at)} · <code>{task.id}</code>
                    </small>
                  </div>
                  <div className="right">
                    <StatusPill tone={meta.tone}>{meta.label}</StatusPill>
                  </div>
                </Link>
              )
            })
          ) : (
            <EmptyState title="没有任务" description="这个会话还没产生任务。" />
          )}
        </ContentSection>

        <ContentSection title="审批记录">
          {approvals.length ? (
            approvals.map((approval) => {
              const approvalMeta = statusMeta(
                APPROVAL_STATUS_META,
                approval.approval_status,
              )
              const toolMeta = statusMeta(
                TOOL_EXECUTION_META,
                approval.tool_execution_status,
              )
              return (
                <Link
                  key={approval.id}
                  className="record"
                  to={`/audit/${approval.thread_id}/${approval.id}`}
                >
                  <div>
                    <b>
                      {approval.tool_name} ·{' '}
                      {approval.target_path ?? '(无目标路径)'}
                    </b>
                    <small>
                      {formatTime(approval.created_at)} · 工具执行：{toolMeta.label}
                    </small>
                  </div>
                  <div className="right">
                    <StatusPill tone={approvalMeta.tone}>
                      {approvalMeta.label}
                    </StatusPill>
                  </div>
                </Link>
              )
            })
          ) : (
            <EmptyState
              title="没有审批记录"
              description="这个会话没有产生需要人工确认的操作。"
            />
          )}
        </ContentSection>
      </div>
    </div>
  )
}

// ── AI-ASSISTED ── 本文件由 AI 生成，待人工复核 ──
// 复核重点：审计以线程卡片为顶层分组；搜索/筛选只作用于 Demo 数据。

import { useMemo, useState } from 'react'

import { Link } from '../app/Link'
import { Icon } from '../components/ui/Icon'
import { PageHeader } from '../components/ui/PageHeader'
import {
  demoApprovals,
  demoThreads,
  getDemoThreadApprovals,
} from '../demo/data'
import { APPROVAL_STATUS_META } from '../features/shared/statusMeta'

function fileName(path: string): string {
  return path.split('/').pop() ?? path
}

function statusClass(status: string): string {
  if (status === 'approved') return 'status-tag done'
  if (status === 'rejected') return 'status-tag rejected'
  return 'status-tag'
}

export function AuditPage() {
  const [query, setQuery] = useState('')
  const [pendingOnly, setPendingOnly] = useState(false)
  const [expandedThread, setExpandedThread] = useState<string | null>(
    demoThreads[0]?.id ?? null,
  )
  const [expandedRecord, setExpandedRecord] = useState<string | null>(null)

  const threads = useMemo(() => {
    const keyword = query.trim().toLowerCase()
    return demoThreads.filter((thread) => {
      const approvals = getDemoThreadApprovals(thread.id)
      if (
        pendingOnly &&
        !approvals.some((approval) => approval.status === 'pending')
      ) {
        return false
      }
      if (!keyword) return true
      return [
        thread.title,
        thread.id,
        thread.preview,
        ...approvals.map(
          (approval) =>
            `${approval.toolName} ${approval.target} ${approval.summary}`,
        ),
      ]
        .join(' ')
        .toLowerCase()
        .includes(keyword)
    })
  }, [query, pendingOnly])

  const pending = demoApprovals.filter(
    (approval) => approval.status === 'pending',
  ).length

  return (
    <div className="page">
      <PageHeader
        title="审批审计"
        description="按线程追溯审批请求、用户决策与关联执行记录。"
        meta={
          <span className="tag amber">● {pending} 项待审批</span>
        }
      />

      <div className="page-content">
        <div className="audit-toolbar">
          <input
            className="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="搜索线程、任务、工具或资源…"
            aria-label="搜索审计记录"
          />
          <button
            type="button"
            className="filter"
            aria-pressed={pendingOnly}
            onClick={() => setPendingOnly((current) => !current)}
          >
            {pendingOnly ? '仅待审批 ×' : '全部状态⌄'}
          </button>
        </div>

        {threads.map((thread) => {
          const approvals = getDemoThreadApprovals(thread.id)
          const isOpen = expandedThread === thread.id
          const pendingCount = approvals.filter(
            (approval) => approval.status === 'pending',
          ).length

          return (
            <div className="thread-card" key={thread.id}>
              <button
                type="button"
                className="thread-card-head"
                aria-expanded={isOpen}
                onClick={() =>
                  setExpandedThread((current) =>
                    current === thread.id ? null : thread.id,
                  )
                }
              >
                <span className="folder" aria-hidden="true">
                  <Icon name="file" size={16} />
                </span>
                <span className="thread-card-info">
                  <b>{thread.title}</b>
                  <small>
                    线程 · {thread.id} · 最近活动 {thread.updatedAt}
                  </small>
                </span>
                <span className="right">
                  {pendingCount ? (
                    <span className="tag amber">
                      {pendingCount} 项待审批
                    </span>
                  ) : (
                    <span className="tag">{approvals.length} 条记录</span>
                  )}
                  <span aria-hidden="true">{isOpen ? '⌃' : '⌄'}</span>
                </span>
              </button>

              {isOpen ? (
                <div className="thread-records">
                  {approvals.map((approval) => {
                    const meta = APPROVAL_STATUS_META[approval.status]
                    const detailOpen = expandedRecord === approval.id
                    return (
                      <div
                        className={
                          detailOpen ? 'record show-detail' : 'record'
                        }
                        key={approval.id}
                      >
                        <div>
                          <Link
                            className="text-link"
                            to={`/audit/${thread.id}/${approval.id}`}
                          >
                            <b>
                              {approval.toolName} ·{' '}
                              {fileName(approval.target)}
                            </b>
                          </Link>
                          <small>
                            Task: {approval.taskId} · Execution:{' '}
                            {approval.executionId} · {approval.requestedAt}
                          </small>
                          <div className="audit-detail">
                            请求快照：{approval.target}
                            <br />
                            决策：{meta.label}
                            {approval.decisionReason
                              ? ` · ${approval.decisionReason}`
                              : ''}
                            <br />
                            执行状态：{approval.toolExecutionStatus}
                            <br />
                            此为本地演示记录，不是后端真实审计数据。
                          </div>
                        </div>
                        <div className="right">
                          <span className={statusClass(approval.status)}>
                            {meta.label}
                          </span>
                          <button
                            type="button"
                            className="pill-btn"
                            onClick={() =>
                              setExpandedRecord((current) =>
                                current === approval.id ? null : approval.id,
                              )
                            }
                          >
                            {detailOpen ? '收起' : '详情'}
                          </button>
                        </div>
                      </div>
                    )
                  })}
                </div>
              ) : null}
            </div>
          )
        })}

        <div className="demo-note">
          ⓘ 以上线程、ID、时间与状态均为演示数据，不代表真实后端记录。
        </div>
      </div>
    </div>
  )
}

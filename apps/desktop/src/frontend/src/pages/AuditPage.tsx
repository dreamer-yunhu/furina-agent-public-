// ── AI-ASSISTED ── 本文件由 AI 生成/改写，待人工复核 ──
// 复核重点：
//   1. 数据来自 `GET /agent/approvals`，按线程分组；离线时显示"未连接"而不是假数据。
//   2. **批准（APPROVED）与执行（SUCCEEDED）是两个字段**，详情里必须分开显示 ——
//      "已批准"永远不等于"执行成功"。
//   3. 搜索只覆盖后端返回的字段（线程标题/工具名/路径）；`args_json` 不在列表里，
//      所以搜不到参数内容，这是接口层面的取舍。

import { useEffect, useMemo, useState } from 'react'

import { Link } from '../app/Link'
import { useBackend } from '../app/providers/backendContext'
import { Icon } from '../components/ui/Icon'
import { PageHeader } from '../components/ui/PageHeader'
import type { StatusTone } from '../components/ui/StatusPill'
import { listApprovals, type ApiApprovalItem } from '../services/api/activity'

const APPROVAL_META: Record<string, { label: string; tone: StatusTone }> = {
  PENDING: { label: '待审批', tone: 'warning' },
  APPROVED: { label: '已批准', tone: 'info' },
  REJECTED: { label: '已拒绝', tone: 'danger' },
  REVOKED: { label: '已撤销', tone: 'neutral' },
}

const EXECUTION_META: Record<string, string> = {
  NOT_STARTED: '未开始',
  RUNNING: '执行中',
  SUCCEEDED: '执行成功',
  FAILED: '执行失败',
  UNKNOWN: '结果未知',
}

function formatTime(iso: string | null): string {
  if (!iso) return '—'
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return iso
  const hhmm = `${String(date.getHours()).padStart(2, '0')}:${String(
    date.getMinutes(),
  ).padStart(2, '0')}`
  return `${date.getMonth() + 1}月${date.getDate()}日 ${hhmm}`
}

interface ThreadGroup {
  threadId: string
  threadTitle: string
  items: ApiApprovalItem[]
}

export function AuditPage() {
  const backend = useBackend()
  const online = backend.status === 'online'

  const [items, setItems] = useState<ApiApprovalItem[]>([])
  const [error, setError] = useState<string | undefined>(undefined)
  const [query, setQuery] = useState('')
  const [pendingOnly, setPendingOnly] = useState(false)
  const [expandedThread, setExpandedThread] = useState<string | null>(null)
  const [expandedRecord, setExpandedRecord] = useState<string | null>(null)

  useEffect(() => {
    if (!online) return
    let cancelled = false
    listApprovals({ size: 100 })
      .then((result) => {
        if (cancelled) return
        setItems(result.items)
      })
      .catch((e: unknown) => {
        if (cancelled) return
        setError(e instanceof Error ? e.message : String(e))
      })
    return () => {
      cancelled = true
    }
  }, [online])

  const filtered = useMemo(() => {
    const keyword = query.trim().toLowerCase()
    return items.filter((item) => {
      if (pendingOnly && item.approval_status !== 'PENDING') return false
      if (!keyword) return true
      return [item.thread_title, item.tool_name, item.target_path ?? ''].some(
        (field) => field.toLowerCase().includes(keyword),
      )
    })
  }, [items, query, pendingOnly])

  const groups = useMemo<ThreadGroup[]>(() => {
    const map = new Map<string, ThreadGroup>()
    for (const item of filtered) {
      const group = map.get(item.thread_id) ?? {
        threadId: item.thread_id,
        threadTitle: item.thread_title,
        items: [],
      }
      group.items.push(item)
      map.set(item.thread_id, group)
    }
    return [...map.values()]
  }, [filtered])

  const pending = items.filter((item) => item.approval_status === 'PENDING').length

  return (
    <div className="page">
      <PageHeader
        title="审批审计"
        description="每次高风险工具调用都会留下一条审批记录；批准与执行状态分开记录。"
        meta={
          pending ? (
            <span className="tag amber">● {pending} 项待审批</span>
          ) : (
            <span className="tag">{items.length} 条记录</span>
          )
        }
      />

      <div className="page-content">
        <div className="audit-toolbar">
          <input
            className="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="搜索线程、工具或目标路径…"
            aria-label="搜索审计记录"
          />
          <button
            type="button"
            className="filter"
            aria-pressed={pendingOnly}
            onClick={() => setPendingOnly((current) => !current)}
          >
            {pendingOnly ? '仅待审批 ×' : '全部状态 ⌄'}
          </button>
        </div>

        {error ? (
          <div className="demo-note" role="alert">
            ⚠ 读取审计记录失败：{error}
          </div>
        ) : null}

        {groups.map((group) => {
          const isOpen = expandedThread === group.threadId
          const groupPending = group.items.filter(
            (item) => item.approval_status === 'PENDING',
          ).length
          return (
            <div className="thread-card" key={group.threadId}>
              <button
                type="button"
                className="thread-card-head"
                aria-expanded={isOpen}
                onClick={() =>
                  setExpandedThread((current) =>
                    current === group.threadId ? null : group.threadId,
                  )
                }
              >
                <span className="folder" aria-hidden="true">
                  <Icon name="file" size={16} />
                </span>
                <span className="thread-card-info">
                  <b>{group.threadTitle}</b>
                  <small>
                    线程 · {group.threadId} · {group.items.length} 条记录
                  </small>
                </span>
                <span className="right">
                  {groupPending ? (
                    <span className="tag amber">{groupPending} 项待审批</span>
                  ) : (
                    <span className="tag">{group.items.length} 条</span>
                  )}
                  <span aria-hidden="true">{isOpen ? '⌃' : '⌄'}</span>
                </span>
              </button>

              {isOpen ? (
                <div className="thread-records">
                  {group.items.map((item) => {
                    const meta = APPROVAL_META[item.approval_status] ?? {
                      label: item.approval_status,
                      tone: 'neutral' as StatusTone,
                    }
                    const detailOpen = expandedRecord === item.id
                    return (
                      <div
                        className={detailOpen ? 'record show-detail' : 'record'}
                        key={item.id}
                      >
                        <div>
                          <Link
                            className="text-link"
                            to={`/chat/${item.thread_id}`}
                          >
                            <b>
                              {item.tool_name} ·{' '}
                              {item.target_path ?? '(无目标路径)'}
                            </b>
                          </Link>
                          <small>
                            Task: {item.task_id} · Execution:{' '}
                            {item.execution_id} · {formatTime(item.created_at)}
                          </small>
                          <div className="audit-detail">
                            审批决定：{meta.label}
                            {item.decided_at
                              ? ` · ${formatTime(item.decided_at)}`
                              : ''}
                            {item.decision_reason
                              ? ` · ${item.decision_reason}`
                              : ''}
                            <br />
                            工具执行：
                            {EXECUTION_META[item.tool_execution_status] ??
                              item.tool_execution_status}
                            <br />
                            <span className="warning">
                              ⚠ 已批准 ≠ 执行成功；两者是独立字段。
                            </span>
                          </div>
                        </div>
                        <div className="right">
                          <span className={`tag ${meta.tone}`}>{meta.label}</span>
                          <button
                            type="button"
                            className="pill-btn"
                            onClick={() =>
                              setExpandedRecord((current) =>
                                current === item.id ? null : item.id,
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

        {online && !groups.length && !error ? (
          <div className="demo-note">
            还没有审批记录。当 Agent 尝试写入文件时，这里会出现第一条记录。
          </div>
        ) : null}

        {!online ? (
          <div className="demo-note">
            ⓘ 未连接本地服务，暂时读不到审计记录。
          </div>
        ) : null}
      </div>
    </div>
  )
}

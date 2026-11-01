// ── AI-ASSISTED ── 本文件由 AI 生成/改写，待人工复核 ──
// 复核重点：
//   1. ★ 从 demo 改成 `GET /agent/executions/{id}`。
//   2. `graph_thread_id` 是传给 LangGraph 的线程键（默认等于 execution_id），
//      排障时要靠它去 checkpoint 里对号，所以必须显示出来。
//   3. 与审批列表分开渲染：审批状态 ≠ 工具执行状态。

import { useEffect, useState } from 'react'

import { Link } from '../app/Link'
import { ContentSection } from '../components/ui/ContentSection'
import { EmptyState } from '../components/ui/EmptyState'
import { KeyValueList } from '../components/ui/KeyValueList'
import { PageHeader } from '../components/ui/PageHeader'
import { StatusPill } from '../components/ui/StatusPill'
import {
  APPROVAL_STATUS_META,
  EXECUTION_STATUS_META,
  TOOL_EXECUTION_META,
  statusMeta,
} from '../features/shared/statusMeta'
import { ApiError } from '../services/api/client'
import { getExecution, type ApiExecutionDetail } from '../services/api/activity'

type LoadState =
  | { kind: 'loading' }
  | { kind: 'error'; message: string; status?: number }
  | { kind: 'ready'; execution: ApiExecutionDetail }

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

export function ExecutionDetailPage({
  taskId,
  executionId,
}: {
  taskId: string
  executionId: string
}) {
  const [state, setState] = useState<LoadState>({ kind: 'loading' })

  useEffect(() => {
    let cancelled = false
    setState({ kind: 'loading' })
    getExecution(executionId)
      .then((execution) => {
        if (!cancelled) setState({ kind: 'ready', execution })
      })
      .catch((error: unknown) => {
        if (cancelled) return
        setState({
          kind: 'error',
          message: error instanceof Error ? error.message : String(error),
          status: error instanceof ApiError ? error.status : undefined,
        })
      })
    return () => {
      cancelled = true
    }
  }, [executionId])

  if (state.kind === 'loading') {
    return (
      <div className="page">
        <PageHeader title="执行详情" description="正在从本地服务读取…" />
        <div className="page-content">
          <EmptyState title="加载中" description={`execution_id = ${executionId}`} />
        </div>
      </div>
    )
  }

  if (state.kind === 'error') {
    const notFound = state.status === 404
    return (
      <div className="page">
        <PageHeader
          title={notFound ? '执行不存在' : '读取执行失败'}
          description={notFound ? '后端没有这条记录。' : '本地服务没有返回可用数据。'}
        />
        <div className="page-content">
          <EmptyState title={notFound ? '404' : '请求失败'} description={state.message} />
          <div className="page__actions">
            <Link className="pill-btn" to={`/tasks/${taskId}`}>
              返回任务
            </Link>
          </div>
        </div>
      </div>
    )
  }

  const execution = state.execution
  const meta = statusMeta(EXECUTION_STATUS_META, execution.status)

  return (
    <div className="page">
      <PageHeader
        title={`执行 ${execution.id.slice(0, 8)}`}
        description="一次 Coder 子图的完整执行记录。"
        meta={
          <>
            <StatusPill tone={meta.tone}>{meta.label}</StatusPill>
            <span className="muted">{formatTime(execution.created_at)}</span>
          </>
        }
      />

      <div className="page-content">
        <ContentSection title="概览">
          <KeyValueList
            items={[
              { label: 'Execution ID', value: <code>{execution.id}</code> },
              {
                label: '所属任务',
                value: (
                  <Link className="text-link" to={`/tasks/${execution.task_id}`}>
                    {execution.task.instruction || execution.task_id}
                  </Link>
                ),
              },
              {
                label: '所属会话',
                value: (
                  <Link className="text-link" to={`/chat/${execution.thread_id}`}>
                    {execution.thread_title}
                  </Link>
                ),
              },
              { label: '状态', value: <StatusPill tone={meta.tone}>{meta.label}</StatusPill> },
              { label: 'graph_thread_id', value: <code>{execution.graph_thread_id}</code> },
              { label: '开始时间', value: formatTime(execution.created_at) },
              {
                label: '结束时间',
                value: execution.finished_at
                  ? formatTime(execution.finished_at)
                  : '进行中',
              },
              ...(execution.validation_failure_reason
                ? [
                    {
                      label: '恢复校验失败',
                      value: execution.validation_failure_reason,
                    },
                  ]
                : []),
            ]}
          />
        </ContentSection>

        <ContentSection
          title="本次执行的审批"
          description="审批决定与工具实际执行是两个独立字段。"
        >
          {execution.approvals.length ? (
            execution.approvals.map((approval) => {
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
              title="本次执行没有审批"
              description="没有触发需要人工确认的写操作。"
            />
          )}
        </ContentSection>
      </div>
    </div>
  )
}

// ── AI-ASSISTED ── 本文件由 AI 生成/改写，待人工复核 ──
// 复核重点：
//   1. ★ 从 demo 改成 `GET /agent/approvals/{id}`。
//   2. **不显示 diff / 文件内容**：列表与详情接口都不返回 `args_json`
//      （可能很大，且含整段文件内容）。要看预览请去会话页的审批卡。
//   3. 审批状态与工具执行状态必须并列显示 —— 「已批准 ≠ 执行成功」。

import { useEffect, useState } from 'react'

import { Link } from '../app/Link'
import { ContentSection } from '../components/ui/ContentSection'
import { EmptyState } from '../components/ui/EmptyState'
import { KeyValueList } from '../components/ui/KeyValueList'
import { PageHeader } from '../components/ui/PageHeader'
import { StatusPill } from '../components/ui/StatusPill'
import {
  APPROVAL_STATUS_META,
  TOOL_EXECUTION_META,
  statusMeta,
} from '../features/shared/statusMeta'
import { ApiError } from '../services/api/client'
import { getApproval, type ApiApprovalDetail } from '../services/api/activity'

type LoadState =
  | { kind: 'loading' }
  | { kind: 'error'; message: string; status?: number }
  | { kind: 'ready'; approval: ApiApprovalDetail }

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

export function AuditApprovalDetailPage({
  approvalId,
}: {
  threadId: string
  approvalId: string
}) {
  const [state, setState] = useState<LoadState>({ kind: 'loading' })

  useEffect(() => {
    let cancelled = false
    setState({ kind: 'loading' })
    getApproval(approvalId)
      .then((approval) => {
        if (!cancelled) setState({ kind: 'ready', approval })
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
  }, [approvalId])

  if (state.kind === 'loading') {
    return (
      <div className="page">
        <PageHeader title="审批记录" description="正在从本地服务读取…" />
        <div className="page-content">
          <EmptyState title="加载中" description={`approval_id = ${approvalId}`} />
        </div>
      </div>
    )
  }

  if (state.kind === 'error') {
    const notFound = state.status === 404
    return (
      <div className="page">
        <PageHeader
          title={notFound ? '审批记录不存在' : '读取审批失败'}
          description={notFound ? '后端没有这条记录。' : '本地服务没有返回可用数据。'}
        />
        <div className="page-content">
          <EmptyState title={notFound ? '404' : '请求失败'} description={state.message} />
          <div className="page__actions">
            <Link className="pill-btn" to="/audit">
              返回审计
            </Link>
          </div>
        </div>
      </div>
    )
  }

  const approval = state.approval
  const approvalMeta = statusMeta(APPROVAL_STATUS_META, approval.approval_status)
  const toolMeta = statusMeta(TOOL_EXECUTION_META, approval.tool_execution_status)

  return (
    <div className="page">
      <PageHeader
        title={approval.tool_name}
        description={approval.target_path ?? '(无目标路径)'}
        meta={
          <>
            <StatusPill tone={approvalMeta.tone}>{approvalMeta.label}</StatusPill>
            <span className="muted">{formatTime(approval.created_at)}</span>
          </>
        }
      />

      <div className="page-content">
        <ContentSection title="审批">
          <KeyValueList
            items={[
              { label: 'Approval ID', value: <code>{approval.id}</code> },
              {
                label: '所属会话',
                value: (
                  <Link className="text-link" to={`/chat/${approval.thread_id}`}>
                    {approval.thread_title}
                  </Link>
                ),
              },
              {
                label: '所属任务',
                value: (
                  <Link className="text-link" to={`/tasks/${approval.task_id}`}>
                    {approval.task.instruction || approval.task_id}
                  </Link>
                ),
              },
              {
                label: '所属执行',
                value: (
                  <Link
                    className="text-link"
                    to={`/tasks/${approval.task_id}/executions/${approval.execution_id}`}
                  >
                    <code>{approval.execution_id}</code>
                  </Link>
                ),
              },
              {
                label: '审批决定',
                value: (
                  <StatusPill tone={approvalMeta.tone}>
                    {approvalMeta.label}
                  </StatusPill>
                ),
              },
              {
                label: '工具执行',
                value: <StatusPill tone={toolMeta.tone}>{toolMeta.label}</StatusPill>,
              },
              { label: '请求时间', value: formatTime(approval.created_at) },
              { label: '决定时间', value: formatTime(approval.decided_at) },
              {
                label: '决定理由',
                value: approval.decision_reason ?? '—',
              },
            ]}
          />
          <p className="demo-note">
            ⚠ 已批准 ≠ 执行成功：上面两个状态是独立字段。变更预览（diff）不在本接口返回，请回会话页查看审批卡。
          </p>
        </ContentSection>
      </div>
    </div>
  )
}

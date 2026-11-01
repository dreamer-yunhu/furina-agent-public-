// ── AI-ASSISTED ── 本文件由 AI 生成/改写，待人工复核 ──
// 复核重点：
//   1. ★ 整页从「查 demo 表」改成「调 GET /agent/tasks/{id}」。
//      demo 版查不到就显示"Demo 数据中没有这个任务"，真实任务永远进不去。
//   2. 三种非正常态必须分开显示：加载中 / 请求失败（含后端未连接）/ 404。
//      混成一个"任务不存在"会让人误以为数据丢了。
//   3. 一个 Task 可以有多次 Execution，**全部列出**，历史不覆盖。

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
  TASK_STATUS_META,
  TOOL_EXECUTION_META,
  statusMeta,
} from '../features/shared/statusMeta'
import { ApiError } from '../services/api/client'
import { getTask, type ApiTaskDetail } from '../services/api/activity'

type LoadState =
  | { kind: 'loading' }
  | { kind: 'error'; message: string; status?: number }
  | { kind: 'ready'; task: ApiTaskDetail }

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

export function TaskDetailPage({ taskId }: { taskId: string }) {
  const [state, setState] = useState<LoadState>({ kind: 'loading' })

  useEffect(() => {
    let cancelled = false
    setState({ kind: 'loading' })
    getTask(taskId)
      .then((task) => {
        if (!cancelled) setState({ kind: 'ready', task })
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
  }, [taskId])

  if (state.kind === 'loading') {
    return (
      <div className="page">
        <PageHeader title="任务详情" description="正在从本地服务读取…" />
        <div className="page-content">
          <EmptyState title="加载中" description={`task_id = ${taskId}`} />
        </div>
      </div>
    )
  }

  if (state.kind === 'error') {
    const notFound = state.status === 404
    return (
      <div className="page">
        <PageHeader
          title={notFound ? '任务不存在' : '读取任务失败'}
          description={notFound ? '后端没有这条记录。' : '本地服务没有返回可用数据。'}
        />
        <div className="page-content">
          <EmptyState
            title={notFound ? '404' : '请求失败'}
            description={state.message}
          />
          <div className="page__actions">
            <Link className="pill-btn" to="/tasks">
              返回任务列表
            </Link>
          </div>
        </div>
      </div>
    )
  }

  const task = state.task
  const status = statusMeta(TASK_STATUS_META, task.status)

  return (
    <div className="page">
      <PageHeader
        title={task.instruction || '(无指令)'}
        description="任务概览、Execution 历史与关联审批。"
        meta={
          <>
            <StatusPill tone={status.tone}>{status.label}</StatusPill>
            <span className="muted">更新于 {formatTime(task.updated_at)}</span>
          </>
        }
      />

      <div className="page-content">
        <ContentSection title="概览">
          <KeyValueList
            items={[
              { label: 'Task ID', value: <code>{task.id}</code> },
              {
                label: '所属会话',
                value: (
                  <Link className="text-link" to={`/chat/${task.thread_id}`}>
                    {task.thread_title}
                  </Link>
                ),
              },
              { label: '任务状态', value: <StatusPill tone={status.tone}>{status.label}</StatusPill> },
              {
                label: 'Execution 数量',
                value: String(task.executions.length),
              },
              ...(task.failure_reason
                ? [{ label: '失败原因', value: task.failure_reason }]
                : []),
            ]}
          />
        </ContentSection>

        <ContentSection
          title="Execution 历史"
          description="同一 Task 的历次执行全部保留，不覆盖旧记录。"
        >
          {task.executions.length ? (
            task.executions.map((execution) => {
              const meta = statusMeta(EXECUTION_STATUS_META, execution.status)
              return (
                <Link
                  key={execution.id}
                  className="record"
                  to={`/tasks/${task.id}/executions/${execution.id}`}
                >
                  <div>
                    <b className="mono">{execution.id}</b>
                    <small>
                      {formatTime(execution.created_at)}
                      {execution.finished_at
                        ? ` → ${formatTime(execution.finished_at)}`
                        : ' → 进行中'}
                      {execution.validation_failure_reason
                        ? ` · ${execution.validation_failure_reason}`
                        : ''}
                    </small>
                  </div>
                  <div className="right">
                    <StatusPill tone={meta.tone}>{meta.label}</StatusPill>
                  </div>
                </Link>
              )
            })
          ) : (
            <EmptyState
              title="还没有 Execution"
              description="这个任务尚未开始执行。"
            />
          )}
        </ContentSection>

        <ContentSection title="关联审批">
          {task.approvals.length ? (
            task.approvals.map((approval) => {
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
              title="没有关联审批"
              description="这个任务没有产生需要人工审批的工具调用。"
            />
          )}
        </ContentSection>
      </div>
    </div>
  )
}

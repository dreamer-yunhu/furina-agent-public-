// ── AI-ASSISTED ── 本文件由 AI 生成/改写，待人工复核 ──
// 复核重点：
//   1. ★ 整块原本读 demo 数据（14 处）。现在按路由调用对应真实接口，
//      拿不到就显示错误原因，**不再回落到演示数据**。
//   2. 面板只放摘要，不重复中央工作区；详情一律给链接。
//   3. 每个分支各自独立请求，某个接口失败只影响当前面板。

import { useEffect, useState } from 'react'

import { Link } from '../../app/Link'
import type { RouteMatch } from '../../app/router'
import { StatusPill } from '../../components/ui/StatusPill'
import {
  APPROVAL_STATUS_META,
  EXECUTION_STATUS_META,
  TASK_STATUS_META,
  TOOL_EXECUTION_META,
  statusMeta,
} from '../shared/statusMeta'
import {
  getApproval,
  getExecution,
  getTask,
  listApprovals,
  listTasks,
  type ApiApprovalDetail,
  type ApiExecutionDetail,
  type ApiTaskDetail,
} from '../../services/api/activity'

type Async<T> =
  | { kind: 'loading' }
  | { kind: 'error'; message: string }
  | { kind: 'ready'; data: T }

function useAsync<T>(
  loader: () => Promise<T>,
  deps: unknown[],
): Async<T> {
  const [state, setState] = useState<Async<T>>({ kind: 'loading' })
  useEffect(() => {
    let cancelled = false
    setState({ kind: 'loading' })
    loader()
      .then((data) => {
        if (!cancelled) setState({ kind: 'ready', data })
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setState({
            kind: 'error',
            message: error instanceof Error ? error.message : String(error),
          })
        }
      })
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)
  return state
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="field">
      <span className="label">{label}</span>
      <div>{children}</div>
    </div>
  )
}

function Loading() {
  return <p className="muted">读取中…</p>
}

function Failed({ message }: { message: string }) {
  return <p className="demo-note">读取失败：{message}</p>
}

function TaskInspector({ taskId }: { taskId: string }) {
  const state = useAsync<ApiTaskDetail>(() => getTask(taskId), [taskId])
  if (state.kind === 'loading') return <Loading />
  if (state.kind === 'error') return <Failed message={state.message} />
  const task = state.data
  const meta = statusMeta(TASK_STATUS_META, task.status)
  return (
    <div className="kv-list">
      <Field label="任务">
        <Link className="text-link" to={`/tasks/${task.id}`}>
          {task.instruction || task.id}
        </Link>
      </Field>
      <Field label="状态">
        <StatusPill tone={meta.tone}>{meta.label}</StatusPill>
      </Field>
      <Field label="会话">
        <Link className="text-link" to={`/chat/${task.thread_id}`}>
          {task.thread_title}
        </Link>
      </Field>
      <Field label="执行次数">{task.executions.length}</Field>
      <Field label="审批数">{task.approvals.length}</Field>
    </div>
  )
}

function ExecutionInspector({ executionId }: { executionId: string }) {
  const state = useAsync<ApiExecutionDetail>(
    () => getExecution(executionId),
    [executionId],
  )
  if (state.kind === 'loading') return <Loading />
  if (state.kind === 'error') return <Failed message={state.message} />
  const execution = state.data
  const meta = statusMeta(EXECUTION_STATUS_META, execution.status)
  return (
    <div className="kv-list">
      <Field label="执行">
        <Link
          className="text-link"
          to={`/tasks/${execution.task_id}/executions/${execution.id}`}
        >
          {execution.id.slice(0, 8)}
        </Link>
      </Field>
      <Field label="状态">
        <StatusPill tone={meta.tone}>{meta.label}</StatusPill>
      </Field>
      <Field label="所属任务">
        <Link className="text-link" to={`/tasks/${execution.task_id}`}>
          {execution.task.instruction || execution.task_id}
        </Link>
      </Field>
      <Field label="审批数">{execution.approvals.length}</Field>
    </div>
  )
}

function ApprovalInspector({ approvalId }: { approvalId: string }) {
  const state = useAsync<ApiApprovalDetail>(
    () => getApproval(approvalId),
    [approvalId],
  )
  if (state.kind === 'loading') return <Loading />
  if (state.kind === 'error') return <Failed message={state.message} />
  const approval = state.data
  const approvalMeta = statusMeta(APPROVAL_STATUS_META, approval.approval_status)
  const toolMeta = statusMeta(TOOL_EXECUTION_META, approval.tool_execution_status)
  return (
    <div className="kv-list">
      <Field label="工具">{approval.tool_name}</Field>
      <Field label="目标">{approval.target_path ?? '—'}</Field>
      <Field label="审批决定">
        <StatusPill tone={approvalMeta.tone}>{approvalMeta.label}</StatusPill>
      </Field>
      <Field label="工具执行">
        <StatusPill tone={toolMeta.tone}>{toolMeta.label}</StatusPill>
      </Field>
      <Field label="所属任务">
        <Link className="text-link" to={`/tasks/${approval.task_id}`}>
          {approval.task.instruction || approval.task_id}
        </Link>
      </Field>
    </div>
  )
}

function ThreadInspector({ threadId }: { threadId: string }) {
  const state = useAsync(
    () =>
      Promise.all([
        listTasks(1, 100, threadId),
        listApprovals({ threadId, size: 100 }),
      ]),
    [threadId],
  )
  if (state.kind === 'loading') return <Loading />
  if (state.kind === 'error') return <Failed message={state.message} />
  const [tasks, approvals] = state.data
  return (
    <div className="kv-list">
      <Field label="线程">
        <Link className="text-link" to={`/audit/${threadId}`}>
          {threadId}
        </Link>
      </Field>
      <Field label="任务数">{tasks.total}</Field>
      <Field label="审批数">{approvals.total}</Field>
      <Field label="进入会话">
        <Link className="text-link" to={`/chat/${threadId}`}>
          打开
        </Link>
      </Field>
    </div>
  )
}

export function RouteInspector({ match }: { match: RouteMatch }) {
  switch (match.name) {
    case 'chat':
      return match.params.threadId ? (
        <ThreadInspector threadId={match.params.threadId} />
      ) : (
        <p className="muted">还没有选中会话。</p>
      )
    case 'task-detail':
      return <TaskInspector taskId={match.params.taskId} />
    case 'execution-detail':
      return <ExecutionInspector executionId={match.params.executionId} />
    case 'audit-thread':
      return <ThreadInspector threadId={match.params.threadId} />
    case 'audit-detail':
      return <ApprovalInspector approvalId={match.params.approvalId} />
    default:
      return <p className="muted">这个页面没有可显示的详情。</p>
  }
}

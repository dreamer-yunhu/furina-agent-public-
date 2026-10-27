// ── AI-ASSISTED ── 本文件由 AI 生成，待人工复核 ──
// 复核重点：
//   1. 详情面板只展示与当前路由相关的摘要，不重复中央工作区。
//   2. 所有数据来自 demo/data.ts；没有数据时明确说「Demo 未包含」。
//   3. 审批状态与工具执行状态分别展示。

import { Link } from '../../app/Link'
import type { RouteMatch } from '../../app/router'
import { StatusPill } from '../../components/ui/StatusPill'
import {
  getDemoApproval,
  getDemoExecution,
  getDemoTask,
  getDemoThread,
  getDemoThreadApprovals,
  getDemoThreadTasks,
} from '../../demo/data'
import type { DemoTask } from '../../demo/types'
import {
  APPROVAL_STATUS_META,
  RISK_META,
  RUN_STATUS_META,
  TOOL_STATUS_META,
} from '../shared/statusMeta'

interface RouteInspectorProps {
  match: RouteMatch
}

function latestExecution(task: DemoTask) {
  return task.executions[task.executions.length - 1]
}

function ChatInspector({ threadId }: { threadId?: string }) {
  const thread = threadId ? getDemoThread(threadId) : undefined
  const tasks = thread ? getDemoThreadTasks(thread.id) : []
  const task = tasks[0]
  const execution = task ? latestExecution(task) : undefined
  const pending = thread
    ? getDemoThreadApprovals(thread.id).filter(
        (approval) => approval.status === 'pending',
      )
    : []

  return (
    <div className="kv-list">
      <div className="field">
        <span className="label">线程</span>
        <div>{thread?.title ?? '新会话（尚未创建）'}</div>
      </div>
      <div className="field">
        <span className="label">当前任务</span>
        <div>
          {task ? (
            <Link className="text-link" to={`/tasks/${task.id}`}>
              {task.title}
            </Link>
          ) : (
            '尚未创建'
          )}
        </div>
      </div>
      <div className="field">
        <span className="label">最新 Execution</span>
        <div>
          {execution ? (
            <Link
              className="text-link"
              to={`/tasks/${task?.id}/executions/${execution.id}`}
            >
              <code>{execution.id}</code>
            </Link>
          ) : (
            '—'
          )}
        </div>
      </div>
      <div className="field">
        <span className="label">待审批</span>
        <div>
          {pending.length ? (
            <StatusPill tone="warning">{pending.length} 条</StatusPill>
          ) : (
            '无'
          )}
        </div>
      </div>

      {execution ? (
        <div className="detail-row">
          <b>最近工具调用</b>
          {execution.toolCalls.map((call) => {
            const meta = TOOL_STATUS_META[call.status]
            return (
              <div className="field" key={call.id}>
                <div>
                  <code>{call.name}</code>{' '}
                  <StatusPill tone={meta.tone}>{meta.label}</StatusPill>
                </div>
                <span className="muted">{call.target}</span>
              </div>
            )
          })}
        </div>
      ) : null}

      {pending.length ? (
        <div className="detail-row">
          <b>待处理审批</b>
          {pending.map((approval) => (
            <Link
              key={approval.id}
              className="text-link"
              to={`/audit/${approval.threadId}/${approval.id}`}
            >
              查看审批：{approval.toolName} · {approval.target}
            </Link>
          ))}
        </div>
      ) : null}
    </div>
  )
}

export function RouteInspector({ match }: RouteInspectorProps) {
  switch (match.name) {
    case 'chat':
      return <ChatInspector threadId={match.params.threadId} />

    case 'task-detail': {
      const task = getDemoTask(match.params.taskId)
      if (!task) {
        return (
          <div className="kv-list">
            <div className="field">
              <span className="label">Task ID</span>
              <code>{match.params.taskId}</code>
            </div>
            <span className="muted">Demo 数据未包含该任务。</span>
          </div>
        )
      }
      const thread = getDemoThread(task.threadId)
      const meta = RUN_STATUS_META[task.status]
      return (
        <div className="kv-list">
          <div className="field">
            <span className="label">Task ID</span>
            <code>{task.id}</code>
          </div>
          <div className="field">
            <span className="label">状态</span>
            <StatusPill tone={meta.tone}>{meta.label}</StatusPill>
          </div>
          <div className="field">
            <span className="label">会话</span>
            <div>{thread?.title ?? task.threadId}</div>
          </div>
          <div className="field">
            <span className="label">Execution</span>
            <div>{task.executions.length}</div>
          </div>
          <div className="field">
            <span className="label">审批</span>
            <div>{task.approvalIds.length}</div>
          </div>
        </div>
      )
    }

    case 'execution-detail': {
      const task = getDemoTask(match.params.taskId)
      const execution = getDemoExecution(
        match.params.taskId,
        match.params.executionId,
      )
      if (!task || !execution) {
        return (
          <div className="kv-list">
            <div className="field">
              <span className="label">Execution ID</span>
              <code>{match.params.executionId}</code>
            </div>
            <span className="muted">Demo 数据未包含该执行。</span>
          </div>
        )
      }
      const meta = RUN_STATUS_META[execution.status]
      return (
        <div className="kv-list">
          <div className="field">
            <span className="label">Execution ID</span>
            <code>{execution.id}</code>
          </div>
          <div className="field">
            <span className="label">所属 Task</span>
            <div>{task.title}</div>
          </div>
          <div className="field">
            <span className="label">状态</span>
            <StatusPill tone={meta.tone}>{meta.label}</StatusPill>
          </div>
          <div className="field">
            <span className="label">工具调用</span>
            <div>{execution.toolCalls.length}</div>
          </div>
          <div className="field">
            <span className="label">开始时间</span>
            <div>{execution.startedAt}</div>
          </div>
        </div>
      )
    }

    case 'audit-thread': {
      const thread = getDemoThread(match.params.threadId)
      if (!thread) {
        return (
          <div className="kv-list">
            <div className="field">
              <span className="label">Thread ID</span>
              <code>{match.params.threadId}</code>
            </div>
            <span className="muted">Demo 数据未包含该线程。</span>
          </div>
        )
      }
      const tasks = getDemoThreadTasks(thread.id)
      const approvals = getDemoThreadApprovals(thread.id)
      const pending = approvals.filter(
        (approval) => approval.status === 'pending',
      ).length
      const meta = RUN_STATUS_META[thread.status]
      return (
        <div className="kv-list">
          <div className="field">
            <span className="label">Thread ID</span>
            <code>{thread.id}</code>
          </div>
          <div className="field">
            <span className="label">状态</span>
            <StatusPill tone={meta.tone}>{meta.label}</StatusPill>
          </div>
          <div className="field">
            <span className="label">任务</span>
            <div>{tasks.length}</div>
          </div>
          <div className="field">
            <span className="label">审批</span>
            <div>{approvals.length} 条</div>
          </div>
          <div className="field">
            <span className="label">待处理</span>
            <div>{pending}</div>
          </div>
        </div>
      )
    }

    case 'audit-detail': {
      const approval = getDemoApproval(match.params.approvalId)
      if (!approval || approval.threadId !== match.params.threadId) {
        return (
          <div className="kv-list">
            <div className="field">
              <span className="label">Approval ID</span>
              <code>{match.params.approvalId}</code>
            </div>
            <span className="muted">Demo 数据未包含该审批。</span>
          </div>
        )
      }
      const approvalMeta = APPROVAL_STATUS_META[approval.status]
      const toolMeta = TOOL_STATUS_META[approval.toolExecutionStatus]
      const riskMeta = RISK_META[approval.risk]
      return (
        <div className="kv-list">
          <div className="field">
            <span className="label">Approval ID</span>
            <code>{approval.id}</code>
          </div>
          <div className="field">
            <span className="label">审批</span>
            <StatusPill tone={approvalMeta.tone}>
              {approvalMeta.label}
            </StatusPill>
          </div>
          <div className="field">
            <span className="label">执行</span>
            <StatusPill tone={toolMeta.tone}>{toolMeta.label}</StatusPill>
          </div>
          <div className="field">
            <span className="label">风险</span>
            <StatusPill tone={riskMeta.tone} dot={false}>
              {riskMeta.label}
            </StatusPill>
          </div>
          <div className="field">
            <span className="label">工具</span>
            <code>{approval.toolName}</code>
          </div>
        </div>
      )
    }

    case 'approval-detail':
      return (
        <div className="kv-list">
          <div className="field">
            <span className="label">Approval ID</span>
            <code>{match.params.approvalRequestId}</code>
          </div>
          <span className="muted">旧入口；Demo 数据见审计页。</span>
        </div>
      )

    default:
      return null
  }
}

// ── AI-ASSISTED ── 本文件由 AI 生成，待人工复核 ──
// 复核重点：Execution 状态、审批状态、工具执行状态分别展示。

import { Link } from '../app/Link'
import { ContentSection } from '../components/ui/ContentSection'
import { EmptyState } from '../components/ui/EmptyState'
import { KeyValueList } from '../components/ui/KeyValueList'
import { PageHeader } from '../components/ui/PageHeader'
import { StatusPill } from '../components/ui/StatusPill'
import {
  demoApprovals,
  getDemoExecution,
  getDemoTask,
} from '../demo/data'
import {
  APPROVAL_STATUS_META,
  RUN_STATUS_META,
  TOOL_STATUS_META,
} from '../features/shared/statusMeta'

interface ExecutionDetailPageProps {
  taskId: string
  executionId: string
}

export function ExecutionDetailPage({
  taskId,
  executionId,
}: ExecutionDetailPageProps) {
  const task = getDemoTask(taskId)
  const execution = getDemoExecution(taskId, executionId)

  if (!task || !execution) {
    return (
      <div className="page">
        <PageHeader
          title="执行不存在"
          description="Demo 数据中没有这次 Execution。"
        />
        <div className="page-content">
          <EmptyState
            title="找不到执行记录"
            description={`task_id = ${taskId} / execution_id = ${executionId}`}
          />
          <div className="page__actions">
            <Link className="pill-btn" to={`/tasks/${taskId}`}>
              返回任务详情
            </Link>
          </div>
        </div>
      </div>
    )
  }

  const meta = RUN_STATUS_META[execution.status]
  const approvals = demoApprovals.filter(
    (approval) => approval.executionId === execution.id,
  )

  return (
    <div className="page">
      <PageHeader
        title="执行详情"
        description={execution.summary}
        meta={
          <>
            <StatusPill tone={meta.tone}>{meta.label}</StatusPill>
            <span className="tag">Demo 数据</span>
            <Link className="text-link" to={`/tasks/${taskId}`}>
              返回任务
            </Link>
          </>
        }
      />

      <div className="page-content">
        <ContentSection title="执行概览">
          <KeyValueList
            items={[
              {
                label: 'Task',
                value: (
                  <Link className="text-link" to={`/tasks/${task.id}`}>
                    {task.title}
                  </Link>
                ),
              },
              { label: 'Execution ID', value: <code>{execution.id}</code> },
              {
                label: '执行状态',
                value: <StatusPill tone={meta.tone}>{meta.label}</StatusPill>,
              },
              {
                label: '开始 / 结束',
                value: `${execution.startedAt}${
                  execution.finishedAt
                    ? ` → ${execution.finishedAt}`
                    : ' → 进行中'
                }`,
              },
            ]}
          />
        </ContentSection>

        <ContentSection title="工具调用">
          {execution.toolCalls.map((call) => {
            const callMeta = TOOL_STATUS_META[call.status]
            return (
              <div key={call.id} className="record">
                <div>
                  <b className="mono">{call.name}</b>
                  <small>
                    {call.target} · {call.summary} · {call.at}
                  </small>
                </div>
                <div className="right">
                  <StatusPill tone={callMeta.tone}>{callMeta.label}</StatusPill>
                </div>
              </div>
            )
          })}
        </ContentSection>

        <ContentSection title="关联审批">
          {approvals.length ? (
            approvals.map((approval) => {
              const approvalMeta = APPROVAL_STATUS_META[approval.status]
              return (
                <Link
                  key={approval.id}
                  className="record"
                  to={`/audit/${approval.threadId}/${approval.id}`}
                >
                  <div>
                    <b>
                      {approval.toolName} · {approval.target}
                    </b>
                    <small>
                      {approval.requestedAt} · {approval.summary}
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
              title="这次执行没有审批"
              description="所有工具调用都是只读或安全操作。"
            />
          )}
        </ContentSection>

        <p className="demo-note">
          Demo 数据：工具结果是本地演示；UNKNOWN / 失败状态不会被自动重放。
        </p>
      </div>
    </div>
  )
}

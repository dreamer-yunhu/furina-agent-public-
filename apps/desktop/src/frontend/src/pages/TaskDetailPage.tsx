// ── AI-ASSISTED ── 本文件由 AI 生成，待人工复核 ──
// 复核重点：一个 Task 可以有多个 Execution；历史列表不覆盖旧记录。

import { Link } from '../app/Link'
import { ContentSection } from '../components/ui/ContentSection'
import { EmptyState } from '../components/ui/EmptyState'
import { KeyValueList } from '../components/ui/KeyValueList'
import { PageHeader } from '../components/ui/PageHeader'
import { StatusPill } from '../components/ui/StatusPill'
import {
  getDemoApproval,
  getDemoTask,
  getDemoThread,
} from '../demo/data'
import type { DemoApproval } from '../demo/types'
import {
  APPROVAL_STATUS_META,
  RUN_STATUS_META,
} from '../features/shared/statusMeta'

interface TaskDetailPageProps {
  taskId: string
}

export function TaskDetailPage({ taskId }: TaskDetailPageProps) {
  const task = getDemoTask(taskId)

  if (!task) {
    return (
      <div className="page">
        <PageHeader title="任务不存在" description="Demo 数据中没有这个任务。" />
        <div className="page-content">
          <EmptyState
            title="找不到任务"
            description={`Demo 数据未包含 task_id = ${taskId}`}
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

  const thread = getDemoThread(task.threadId)
  const statusMeta = RUN_STATUS_META[task.status]
  const approvals = task.approvalIds
    .map((id) => getDemoApproval(id))
    .filter((item): item is DemoApproval => Boolean(item))

  return (
    <div className="page">
      <PageHeader
        title={task.title}
        description="任务概览、Execution 历史与关联审批。"
        meta={
          <>
            <StatusPill tone={statusMeta.tone}>{statusMeta.label}</StatusPill>
            <span className="tag">Demo 数据</span>
            <span className="muted">更新于 {task.updatedAt}</span>
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
                value: thread ? (
                  <Link className="text-link" to={`/chat/${thread.id}`}>
                    {thread.title}
                  </Link>
                ) : (
                  <span className="muted">{task.threadId}</span>
                ),
              },
              {
                label: '任务状态',
                value: (
                  <StatusPill tone={statusMeta.tone}>
                    {statusMeta.label}
                  </StatusPill>
                ),
              },
              {
                label: 'Execution 数量',
                value: String(task.executions.length),
              },
            ]}
          />
        </ContentSection>

        <ContentSection
          title="Execution 历史"
          description="同一 Task 的历次执行全部保留，不覆盖旧记录。"
        >
          {task.executions.length ? (
            task.executions.map((execution) => {
              const meta = RUN_STATUS_META[execution.status]
              return (
                <Link
                  key={execution.id}
                  className="record"
                  to={`/tasks/${task.id}/executions/${execution.id}`}
                >
                  <div>
                    <b className="mono">{execution.id}</b>
                    <small>
                      {execution.startedAt}
                      {execution.finishedAt
                        ? ` → ${execution.finishedAt}`
                        : ' → 进行中'}{' '}
                      · {execution.summary}
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
          {approvals.length ? (
            approvals.map((approval) => {
              const meta = APPROVAL_STATUS_META[approval.status]
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
                    <StatusPill tone={meta.tone}>{meta.label}</StatusPill>
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

        <p className="demo-note">
          Demo 数据：任务与 Execution 均为本地演示；「已完成」不代表所有工具都成功。
        </p>
      </div>
    </div>
  )
}

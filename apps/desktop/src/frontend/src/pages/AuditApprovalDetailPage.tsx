// ── AI-ASSISTED ── 本文件由 AI 生成，待人工复核 ──
// 复核重点：审批请求 → 用户决定 → 工具执行是三个独立阶段；时间线要能看出「批准但失败」。

import { Link } from '../app/Link'
import { ContentSection } from '../components/ui/ContentSection'
import { DemoBadge } from '../components/ui/DemoBadge'
import { EmptyState } from '../components/ui/EmptyState'
import { KeyValueList } from '../components/ui/KeyValueList'
import { PageHeader } from '../components/ui/PageHeader'
import { StatusPill } from '../components/ui/StatusPill'
import {
  getDemoApproval,
  getDemoExecution,
  getDemoTask,
  getDemoThread,
} from '../demo/data'
import {
  APPROVAL_STATUS_META,
  RISK_META,
  RUN_STATUS_META,
  TOOL_STATUS_META,
} from '../features/shared/statusMeta'

interface AuditApprovalDetailPageProps {
  threadId: string
  approvalId: string
}

export function AuditApprovalDetailPage({
  threadId,
  approvalId,
}: AuditApprovalDetailPageProps) {
  const approval = getDemoApproval(approvalId)

  if (!approval || approval.threadId !== threadId) {
    return (
      <div className="page">
        <PageHeader
          title="审批记录不存在"
          description="Demo 数据中没有这条审批记录。"
        />
        <EmptyState
          title="找不到审批记录"
          description={`thread_id = ${threadId} / approval_id = ${approvalId}`}
        />
        <div className="page__actions">
          <Link className="button" to={`/audit/${threadId}`}>
            返回线程
          </Link>
        </div>
      </div>
    )
  }

  const thread = getDemoThread(approval.threadId)
  const task = getDemoTask(approval.taskId)
  const execution = getDemoExecution(approval.taskId, approval.executionId)
  const approvalMeta = APPROVAL_STATUS_META[approval.status]
  const toolMeta = TOOL_STATUS_META[approval.toolExecutionStatus]
  const riskMeta = RISK_META[approval.risk]
  const executionMeta = execution ? RUN_STATUS_META[execution.status] : undefined

  return (
    <div className="page">
      <PageHeader
        title="审批详情"
        description={approval.summary}
        meta={
          <>
            <DemoBadge />
            <StatusPill tone={approvalMeta.tone}>
              {approvalMeta.label}
            </StatusPill>
            <StatusPill tone={riskMeta.tone} dot={false}>
              {riskMeta.label}
            </StatusPill>
            <Link className="text-link" to={`/audit/${threadId}`}>
              返回线程
            </Link>
          </>
        }
      />

      <div className="page-content">
      <ContentSection
        title="决策链"
        description="审批通过不等于执行成功；每一步都要单独核对。"
      >
        <ol className="timeline">
          <li className="timeline__item">
            <span className="timeline__dot timeline__dot--done" />
            <div className="timeline__content">
              <div className="timeline__title">
                <span>审批请求</span>
                <span className="timeline__time">{approval.requestedAt}</span>
              </div>
              <p>
                {approval.toolName} · <code>{approval.target}</code>
              </p>
            </div>
          </li>
          <li className="timeline__item">
            <span
              className={`timeline__dot ${
                approval.status === 'pending'
                  ? 'timeline__dot--pending'
                  : 'timeline__dot--done'
              }`}
            />
            <div className="timeline__content">
              <div className="timeline__title">
                <span>用户决定</span>
                <span className="timeline__time">
                  {approval.decidedAt ?? '等待处理'}
                </span>
              </div>
              <p>
                <StatusPill tone={approvalMeta.tone}>
                  {approvalMeta.label}
                </StatusPill>
                {approval.decidedBy ? ` · ${approval.decidedBy}` : null}
                {approval.decisionReason
                  ? ` · ${approval.decisionReason}`
                  : null}
              </p>
            </div>
          </li>
          <li className="timeline__item">
            <span
              className={`timeline__dot ${
                approval.toolExecutionStatus === 'succeeded'
                  ? 'timeline__dot--done'
                  : approval.toolExecutionStatus === 'failed'
                    ? 'timeline__dot--failed'
                    : 'timeline__dot--pending'
              }`}
            />
            <div className="timeline__content">
              <div className="timeline__title">
                <span>工具执行</span>
                <span className="timeline__time">
                  {execution?.finishedAt ?? '尚未结束'}
                </span>
              </div>
              <p>
                <StatusPill tone={toolMeta.tone}>{toolMeta.label}</StatusPill>
                {approval.toolResult ? ` · ${approval.toolResult}` : null}
              </p>
            </div>
          </li>
        </ol>
      </ContentSection>

      <ContentSection title="请求详情">
        <KeyValueList
          items={[
            { label: 'Approval ID', value: <code>{approval.id}</code> },
            { label: '工具', value: <code>{approval.toolName}</code> },
            { label: '目标资源', value: <code>{approval.target}</code> },
            { label: '操作摘要', value: approval.summary },
            {
              label: '风险等级',
              value: <StatusPill tone={riskMeta.tone}>{riskMeta.label}</StatusPill>,
            },
            {
              label: 'Execution 状态',
              value: executionMeta ? (
                <StatusPill tone={executionMeta.tone}>
                  {executionMeta.label}
                </StatusPill>
              ) : (
                <span className="muted">未知</span>
              ),
            },
          ]}
        />
      </ContentSection>

      <ContentSection title="关联实体">
        <KeyValueList
          items={[
            {
              label: '线程',
              value: thread ? (
                <Link className="text-link" to={`/audit/${thread.id}`}>
                  {thread.title}
                </Link>
              ) : (
                <code>{approval.threadId}</code>
              ),
            },
            {
              label: '任务',
              value: task ? (
                <Link className="text-link" to={`/tasks/${task.id}`}>
                  {task.title}
                </Link>
              ) : (
                <code>{approval.taskId}</code>
              ),
            },
            {
              label: 'Execution',
              value: (
                <Link
                  className="text-link"
                  to={`/tasks/${approval.taskId}/executions/${approval.executionId}`}
                >
                  <code>{approval.executionId}</code>
                </Link>
              ),
            },
          ]}
        />
      </ContentSection>

      <p className="demo-note">
        Demo 数据：这条记录用于演示「已批准但执行失败」；真实后端会由预检与
        old_hash 校验拦截。
      </p>
      </div>
    </div>
  )
}

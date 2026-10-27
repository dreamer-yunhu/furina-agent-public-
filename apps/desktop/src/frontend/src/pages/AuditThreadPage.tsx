// ── AI-ASSISTED ── 本文件由 AI 生成，待人工复核 ──
// 复核重点：线程 → 审批记录 → 具体记录是三级导航；这里只做第二级。

import { Link } from '../app/Link'
import { ContentSection } from '../components/ui/ContentSection'
import { EmptyState } from '../components/ui/EmptyState'
import { KeyValueList } from '../components/ui/KeyValueList'
import { PageHeader } from '../components/ui/PageHeader'
import { StatusPill } from '../components/ui/StatusPill'
import {
  getDemoThread,
  getDemoThreadApprovals,
  getDemoThreadTasks,
} from '../demo/data'
import {
  APPROVAL_STATUS_META,
  RISK_META,
  RUN_STATUS_META,
  TOOL_STATUS_META,
} from '../features/shared/statusMeta'

interface AuditThreadPageProps {
  threadId: string
}

export function AuditThreadPage({ threadId }: AuditThreadPageProps) {
  const thread = getDemoThread(threadId)

  if (!thread) {
    return (
      <div className="page">
        <PageHeader title="线程不存在" description="Demo 数据中没有这个线程。" />
        <div className="page-content">
          <EmptyState
            title="找不到线程"
            description={`Demo 数据未包含 thread_id = ${threadId}`}
          />
          <div className="page__actions">
            <Link className="pill-btn" to="/audit">
              返回审计
            </Link>
          </div>
        </div>
      </div>
    )
  }

  const tasks = getDemoThreadTasks(thread.id)
  const executions = tasks.flatMap((task) => task.executions)
  const approvals = getDemoThreadApprovals(thread.id)
  const pending = approvals.filter(
    (approval) => approval.status === 'pending',
  ).length
  const statusMeta = RUN_STATUS_META[thread.status]

  return (
    <div className="page">
      <PageHeader
        title={thread.title}
        description={thread.preview}
        meta={
          <>
            <StatusPill tone={statusMeta.tone}>{statusMeta.label}</StatusPill>
            <span className="tag">Demo 数据</span>
            <Link className="text-link" to="/audit">
              返回审计
            </Link>
          </>
        }
      />

      <div className="page-content">
        <ContentSection title="线程概览">
          <KeyValueList
            items={[
              { label: 'Thread ID', value: <code>{thread.id}</code> },
              { label: '任务数量', value: String(tasks.length) },
              { label: 'Execution 数量', value: String(executions.length) },
              {
                label: '审批记录',
                value: `${approvals.length} 条（${pending} 条待处理）`,
              },
              { label: '最近活动', value: thread.updatedAt },
            ]}
          />
        </ContentSection>

        <ContentSection
          title="审批记录"
          description="点击一条记录查看审批请求、用户决定、执行结果与关联实体。"
        >
          {approvals.length ? (
            approvals.map((approval) => {
              const approvalMeta = APPROVAL_STATUS_META[approval.status]
              const toolMeta = TOOL_STATUS_META[approval.toolExecutionStatus]
              const riskMeta = RISK_META[approval.risk]
              return (
                <Link
                  key={approval.id}
                  className="record"
                  to={`/audit/${thread.id}/${approval.id}`}
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
                    <StatusPill tone={toolMeta.tone}>
                      {toolMeta.label}
                    </StatusPill>
                    <StatusPill tone={riskMeta.tone} dot={false}>
                      {riskMeta.label}
                    </StatusPill>
                  </div>
                </Link>
              )
            })
          ) : (
            <EmptyState
              title="这个线程还没有审批记录"
              description="只读工具调用不会产生审批。"
            />
          )}
        </ContentSection>

        <p className="demo-note">
          Demo 数据：审批状态与工具执行状态是两套字段，请分别阅读。
        </p>
      </div>
    </div>
  )
}

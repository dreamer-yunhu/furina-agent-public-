// ── AI-ASSISTED ── 本文件由 AI 生成，待人工复核 ──
// 复核重点：approvalRequestId 来自路由参数；审批详情尚未实现查询接口。

import { EmptyState } from '../components/ui/EmptyState'
import { KeyValueList } from '../components/ui/KeyValueList'
import { PageHeader } from '../components/ui/PageHeader'
import { Panel } from '../components/ui/Panel'
import { PlaceholderTag } from '../components/ui/PlaceholderTag'

interface ApprovalDetailPageProps {
  approvalRequestId: string
}

export function ApprovalDetailPage({ approvalRequestId }: ApprovalDetailPageProps) {
  return (
    <div className="page">
      <PageHeader
        title="审批详情"
        description="工具、参数快照、风险与关联执行；真实数据在 F3 接入。"
        meta={<PlaceholderTag label="F3 接入" />}
      />

      <Panel title="审批概览">
        <KeyValueList
          items={[
            {
              label: 'Approval ID',
              value: <code>{approvalRequestId}</code>,
            },
            { label: '关联 Task', value: <PlaceholderTag label="待查询" /> },
            { label: '关联 Execution', value: <PlaceholderTag label="待查询" /> },
            { label: '审批状态', value: <PlaceholderTag label="待查询" /> },
          ]}
        />
      </Panel>

      <Panel title="工具与参数快照">
        <EmptyState
          title="尚未接入审批详情查询"
          description="当前 SSE 载荷只提供 path/diff/approval_id，缺 tool_name、完整参数、风险等级与 deadline。"
          hint="F2 需要补最小查询接口或扩展审批载荷；F3 再实现卡片。"
        />
      </Panel>

      <Panel title="决定与执行结果">
        <EmptyState
          title="尚未接入决定历史"
          description="批准不等于执行成功；决定结果与工具执行结果需要分别读取。"
        />
      </Panel>
    </div>
  )
}

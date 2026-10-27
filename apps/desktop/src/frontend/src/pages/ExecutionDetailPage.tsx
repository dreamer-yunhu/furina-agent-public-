// ── AI-ASSISTED ── 本文件由 AI 生成，待人工复核 ──
// 复核重点：Execution、Approval、ToolExecution 是不同状态，不能合并展示。

import { EmptyState } from '../components/ui/EmptyState'
import { KeyValueList } from '../components/ui/KeyValueList'
import { PageHeader } from '../components/ui/PageHeader'
import { Panel } from '../components/ui/Panel'
import { PlaceholderTag } from '../components/ui/PlaceholderTag'

interface ExecutionDetailPageProps {
  taskId: string
  executionId: string
}

export function ExecutionDetailPage({
  taskId,
  executionId,
}: ExecutionDetailPageProps) {
  return (
    <div className="page">
      <PageHeader
        title="执行详情"
        description="一次 Execution 的状态、工具调用与关联审批。"
        meta={<PlaceholderTag label="F3 接入" />}
      />

      <Panel title="执行概览">
        <KeyValueList
          items={[
            { label: 'Task ID', value: <code>{taskId}</code> },
            { label: 'Execution ID', value: <code>{executionId}</code> },
            { label: '执行状态', value: <PlaceholderTag label="待查询" /> },
            { label: '开始 / 结束时间', value: <span className="muted">F3 接入</span> },
          ]}
        />
      </Panel>

      <Panel title="工具调用历史">
        <EmptyState
          title="尚未接入工具事件查询"
          description="工具执行状态（NOT_STARTED / RUNNING / SUCCEEDED / FAILED / UNKNOWN）需要独立展示。"
        />
      </Panel>

      <Panel title="关联审批与决定">
        <EmptyState
          title="尚未接入审批查询"
          description="批准不等于执行成功；审批状态与工具执行状态必须分开显示。"
        />
      </Panel>
    </div>
  )
}

// ── AI-ASSISTED ── 本文件由 AI 生成，待人工复核 ──
// 复核重点：taskId 来自路由参数，是真实 URL 值，不是伪造数据。

import { EmptyState } from '../components/ui/EmptyState'
import { KeyValueList } from '../components/ui/KeyValueList'
import { PageHeader } from '../components/ui/PageHeader'
import { Panel } from '../components/ui/Panel'
import { PlaceholderTag } from '../components/ui/PlaceholderTag'

interface TaskDetailPageProps {
  taskId: string
}

export function TaskDetailPage({ taskId }: TaskDetailPageProps) {
  return (
    <div className="page">
      <PageHeader
        title="任务详情"
        description="Task 与 Execution 的关联关系；真实数据在 F3 接入。"
        meta={<PlaceholderTag label="F3 接入" />}
      />

      <Panel title="概览">
        <KeyValueList
          items={[
            { label: 'Task ID', value: <code>{taskId}</code> },
            { label: '业务状态', value: <PlaceholderTag label="待查询" /> },
            { label: '当前 Execution', value: <PlaceholderTag label="待查询" /> },
            { label: '更新时间', value: <span className="muted">F3 接入</span> },
          ]}
        />
      </Panel>

      <Panel
        title="Execution 历史"
        description="同一 Task 的历次执行全部保留，不覆盖旧记录。"
      >
        <EmptyState
          title="尚未接入执行查询"
          description="GET /agent/tasks/{taskId}/executions 尚未实现。"
          hint="F3 接入后，这里展示每次执行的状态、起止时间与结果。"
        />
      </Panel>

      <Panel title="关联审批">
        <EmptyState
          title="尚未接入审批查询"
          description="审批与 Execution 绑定；新执行不继承旧执行的授权。"
        />
      </Panel>
    </div>
  )
}

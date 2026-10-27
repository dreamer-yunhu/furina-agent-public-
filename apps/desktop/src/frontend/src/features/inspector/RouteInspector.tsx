// ── AI-ASSISTED ── 本文件由 AI 生成，待人工复核 ──
// 复核重点：按路由决定详情面板内容；F1 只放占位，不伪造执行数据。

import type { RouteMatch } from '../../app/router'
import { KeyValueList } from '../../components/ui/KeyValueList'
import { Panel } from '../../components/ui/Panel'
import { PlaceholderTag } from '../../components/ui/PlaceholderTag'

interface RouteInspectorProps {
  match: RouteMatch
}

export function RouteInspector({ match }: RouteInspectorProps) {
  switch (match.name) {
    case 'task-detail':
      return (
        <Panel title="任务检查器" description="F3 接入真实数据。">
          <KeyValueList
            items={[
              { label: 'Task ID', value: <code>{match.params.taskId}</code> },
              { label: '业务状态', value: <PlaceholderTag label="待查询" /> },
              { label: '当前执行', value: <PlaceholderTag label="待查询" /> },
            ]}
          />
        </Panel>
      )

    case 'execution-detail':
      return (
        <Panel title="执行检查器" description="F3 接入真实数据。">
          <KeyValueList
            items={[
              { label: 'Execution ID', value: <code>{match.params.executionId}</code> },
              { label: '所属 Task', value: <code>{match.params.taskId}</code> },
              { label: '工具执行状态', value: <PlaceholderTag label="待查询" /> },
              { label: '关联审批', value: <PlaceholderTag label="待查询" /> },
            ]}
          />
        </Panel>
      )

    case 'approval-detail':
      return (
        <Panel title="审批检查器" description="F3 接入真实数据。">
          <KeyValueList
            items={[
              {
                label: 'Approval ID',
                value: <code>{match.params.approvalRequestId}</code>,
              },
              { label: '审批状态', value: <PlaceholderTag label="待查询" /> },
              { label: '工具执行状态', value: <PlaceholderTag label="待查询" /> },
            ]}
          />
        </Panel>
      )

    default:
      return null
  }
}

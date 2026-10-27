// ── AI-ASSISTED ── 本文件由 AI 生成，待人工复核 ──
// 复核重点：前端不得在本地把审批标记为成功；决定与恢复是两个操作。

import { EmptyState } from '../components/ui/EmptyState'
import { Notice } from '../components/ui/Notice'
import { PageHeader } from '../components/ui/PageHeader'
import { Panel } from '../components/ui/Panel'
import { PlaceholderTag } from '../components/ui/PlaceholderTag'

export function ApprovalsPage() {
  return (
    <div className="page">
      <PageHeader
        title="审批"
        description="待审批事项与历史记录；真实数据在 F3 接入。"
        meta={<PlaceholderTag label="F3 接入" />}
      />

      <Panel
        title="待审批"
        description="真实数据来源：GET /agent/approvals?status=PENDING（尚未实现）。"
      >
        <EmptyState
          title="暂无待审批事项"
          description="后端尚未提供审批查询接口，前端不生成模拟审批。"
          hint="F3 接入后，这里展示工具名称、参数摘要、目标资源与后端实际提供的风险信息。"
        />
      </Panel>

      <Panel title="历史记录">
        <EmptyState
          title="尚未接入历史审批"
          description="审批决定、执行结果与迟到标记需要分字段展示。"
        />
      </Panel>

      <Notice tone="warning" title="边界">
        审批决定（<code>POST /agent/decisions</code>）与恢复执行（
        <code>POST /agent/resume</code>）是两个不同操作。前端不会绕过后端预检，
        也不会把按钮点击直接当成审批成功。
      </Notice>
    </div>
  )
}

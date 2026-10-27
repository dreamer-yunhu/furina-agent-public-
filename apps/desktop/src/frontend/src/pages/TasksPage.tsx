// ── AI-ASSISTED ── 本文件由 AI 生成，待人工复核 ──
// 复核重点：任务列表接口尚未实现；这里不能放模拟行。

import { EmptyState } from '../components/ui/EmptyState'
import { PageHeader } from '../components/ui/PageHeader'
import { Panel } from '../components/ui/Panel'
import { PlaceholderTag } from '../components/ui/PlaceholderTag'

export function TasksPage() {
  return (
    <div className="page">
      <PageHeader
        title="任务"
        description="任务列表、业务状态、更新时间与当前执行。"
        meta={<PlaceholderTag label="F3 接入" />}
      />

      <Panel
        title="任务列表"
        description="真实数据来源：GET /agent/tasks（尚未实现）。"
      >
        <div className="table-placeholder" aria-hidden="true">
          <span>任务</span>
          <span>业务状态</span>
          <span>更新时间</span>
        </div>
        <EmptyState
          title="暂无任务数据"
          description="后端尚未提供任务查询接口，前端不生成模拟任务。"
          hint="F2 冻结契约，F3 接入列表、抽屉与详情页。"
        />
      </Panel>

      <Panel
        title="筛选与分页"
        description="按状态、Thread、时间筛选；分页参数在 F2 与后端一起确定。"
      >
        <p className="muted">F1 只保留布局位置，不实现交互。</p>
      </Panel>
    </div>
  )
}

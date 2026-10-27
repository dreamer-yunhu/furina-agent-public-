// ── AI-ASSISTED ── 本文件由 AI 生成，待人工复核 ──
// 复核重点：任务卡片对齐原型；点击进入任务详情；数据全部来自 demo/data.ts。

import { Link } from '../app/Link'
import { PageHeader } from '../components/ui/PageHeader'
import { StatusPill } from '../components/ui/StatusPill'
import { demoTasks, getDemoThread } from '../demo/data'
import { RUN_STATUS_META } from '../features/shared/statusMeta'

export function TasksPage() {
  return (
    <div className="page">
      <PageHeader
        title="任务"
        description="任务组织工作目标，执行记录保留每次运行的独立历史。"
        meta={<span className="tag">{demoTasks.length} 个任务</span>}
      />

      <div className="page-content">
        <div className="task-grid">
          {demoTasks.map((task) => {
            const thread = getDemoThread(task.threadId)
            const meta = RUN_STATUS_META[task.status]
            return (
              <Link
                key={task.id}
                className="task-card"
                to={`/tasks/${task.id}`}
              >
                <h3>{task.title}</h3>
                <p>{thread?.preview ?? task.id}</p>
                <div className="meta">
                  <span>
                    Execution · {task.executions.length} · 更新 {task.updatedAt}
                  </span>
                  <StatusPill tone={meta.tone}>{meta.label}</StatusPill>
                </div>
              </Link>
            )
          })}
        </div>

        <div className="demo-note">
          ⓘ 任务列表使用本地示例数据，尚未连接真实 Task/Execution 查询接口。
        </div>
      </div>
    </div>
  )
}

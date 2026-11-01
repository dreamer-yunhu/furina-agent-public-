// ── AI-ASSISTED ── 本文件由 AI 生成/改写，待人工复核 ──
// 复核重点：
//   1. ★ 删掉离线回落 demo 的分支：连不上就是连不上，显示原因，不拿示例数据充数。
//   2. 卡片链接改为**任务详情**（`/tasks/{id}`）—— 后端现在有详情接口了。
//      （上一版因为缺接口只能退而求其次跳到会话。）
//   3. 状态映射统一走 features/shared/statusMeta，不再本文件自带一份。

import { useEffect, useState } from 'react'

import { Link } from '../app/Link'
import { useBackend } from '../app/providers/backendContext'
import { PageHeader } from '../components/ui/PageHeader'
import { StatusPill } from '../components/ui/StatusPill'
import { TASK_STATUS_META, statusMeta } from '../features/shared/statusMeta'
import { listTasks, type ApiTaskItem } from '../services/api/activity'

function formatTime(iso: string): string {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return iso
  const now = new Date()
  const hhmm = `${String(date.getHours()).padStart(2, '0')}:${String(
    date.getMinutes(),
  ).padStart(2, '0')}`
  if (date.toDateString() === now.toDateString()) return `今天 ${hhmm}`
  return `${date.getMonth() + 1}月${date.getDate()}日 ${hhmm}`
}

export function TasksPage() {
  const backend = useBackend()
  const online = backend.status === 'online'

  const [items, setItems] = useState<ApiTaskItem[]>([])
  const [total, setTotal] = useState(0)
  const [error, setError] = useState<string | undefined>(undefined)

  useEffect(() => {
    if (!online) return
    let cancelled = false
    listTasks(1, 30)
      .then((result) => {
        if (cancelled) return
        setItems(result.items)
        setTotal(result.total)
        setError(undefined)
      })
      .catch((e: unknown) => {
        if (cancelled) return
        setError(e instanceof Error ? e.message : String(e))
      })
    return () => {
      cancelled = true
    }
  }, [online])

  return (
    <div className="page">
      <PageHeader
        title="任务"
        description="每次用户输入都会创建一个任务；点卡片进入任务详情。"
        meta={<span className="tag">{online ? `${total} 个任务` : '未连接'}</span>}
      />

      <div className="page-content">
        {!online ? (
          <div className="demo-note" role="alert">
            ⓘ 未连接本地服务
            {backend.error ? `：${backend.error}` : ''}。启动应用后这里会显示真实任务。
          </div>
        ) : null}

        {error ? (
          <div className="demo-note" role="alert">
            ⚠ 读取任务失败：{error}
          </div>
        ) : null}

        <div className="task-grid">
          {items.map((task) => {
            const meta = statusMeta(TASK_STATUS_META, task.status)
            return (
              <Link key={task.id} className="task-card" to={`/tasks/${task.id}`}>
                <h3>{task.instruction || '(无指令)'}</h3>
                <p>{task.thread_title}</p>
                <div className="meta">
                  <span>更新 {formatTime(task.updated_at)}</span>
                  <StatusPill tone={meta.tone}>{meta.label}</StatusPill>
                </div>
              </Link>
            )
          })}
        </div>

        {online && !items.length && !error ? (
          <div className="demo-note">还没有任务：去「会话」里发第一条消息。</div>
        ) : null}
      </div>
    </div>
  )
}

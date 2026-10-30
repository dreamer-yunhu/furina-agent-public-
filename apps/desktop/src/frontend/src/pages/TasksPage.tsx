// ── AI-ASSISTED ── 本文件由 AI 生成/改写，待人工复核 ──
// 复核重点：
//   1. 在线时读 `GET /agent/tasks`，离线回落到 Demo —— 两条路径都要能看到东西。
//   2. 卡片链接指向**所属会话**（`/chat/{thread_id}`），不是任务详情页：
//      后端还没有单任务详情接口，链到详情只会看到"任务不存在"。
//   3. 状态是后端原样字符串，展示文案在这里映射，别在 API 层改值。

import { useEffect, useState } from 'react'

import { Link } from '../app/Link'
import { useBackend } from '../app/providers/backendContext'
import { PageHeader } from '../components/ui/PageHeader'
import { StatusPill, type StatusTone } from '../components/ui/StatusPill'
import { demoTasks, getDemoThread } from '../demo/data'
import { RUN_STATUS_META } from '../features/shared/statusMeta'
import { listTasks, type ApiTaskItem } from '../services/api/activity'

type Tone = StatusTone

const TASK_STATUS_META: Record<string, { label: string; tone: Tone }> = {
  QUEUED: { label: '排队中', tone: 'neutral' },
  RUNNING: { label: '运行中', tone: 'running' },
  WAITING_APPROVAL: { label: '等待审批', tone: 'warning' },
  SUSPENDED: { label: '已挂起', tone: 'danger' },
  COMPLETED: { label: '已完成', tone: 'success' },
  FAILED: { label: '失败', tone: 'danger' },
  CANCELLED: { label: '已取消', tone: 'neutral' },
}

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
        description="每次用户输入都会创建一个任务；点卡片进入它所属的会话。"
        meta={
          <span className="tag">
            {online ? `${total} 个任务` : `Demo · ${demoTasks.length} 个任务`}
          </span>
        }
      />

      <div className="page-content">
        {error ? (
          <div className="demo-note" role="alert">
            ⚠ 读取任务失败：{error}
          </div>
        ) : null}

        <div className="task-grid">
          {online
            ? items.map((task) => {
                const meta =
                  TASK_STATUS_META[task.status] ?? {
                    label: task.status,
                    tone: 'neutral' as Tone,
                  }
                return (
                  <Link
                    key={task.id}
                    className="task-card"
                    to={`/chat/${task.thread_id}`}
                  >
                    <h3>{task.instruction || '(无指令)'}</h3>
                    <p>{task.thread_title}</p>
                    <div className="meta">
                      <span>更新 {formatTime(task.updated_at)}</span>
                      <StatusPill tone={meta.tone}>{meta.label}</StatusPill>
                    </div>
                  </Link>
                )
              })
            : demoTasks.map((task) => {
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
                        Execution · {task.executions.length} · 更新{' '}
                        {task.updatedAt}
                      </span>
                      <StatusPill tone={meta.tone}>{meta.label}</StatusPill>
                    </div>
                  </Link>
                )
              })}
        </div>

        {online && !items.length && !error ? (
          <div className="demo-note">还没有任务：去「会话」里发第一条消息。</div>
        ) : null}

        {!online ? (
          <div className="demo-note">
            ⓘ 未连接本地服务，当前显示的是示例任务。
          </div>
        ) : null}
      </div>
    </div>
  )
}

// ── AI-ASSISTED ── 本文件由 AI 生成，待人工复核 ──
// 复核重点：对齐 Codex 原型的 chat-head：标题 + 标签行 + 审计入口。

import { Link } from '../../app/Link'
import type { DemoThread } from '../../demo/types'

interface ConversationHeaderProps {
  thread?: DemoThread
  threadId?: string
}

export function ConversationHeader({
  thread,
  threadId,
}: ConversationHeaderProps) {
  const pending = thread?.pendingApprovals ?? 0
  const id = thread?.id ?? threadId

  return (
    <header className="chat-head">
      <div>
        <h1>{thread?.title ?? '新建会话'}</h1>
        <div className="subline">
          <span className="tag">
            线程 · {id ?? 'new-chat'}
          </span>
          {pending ? (
            <span className="tag amber">● {pending} 项待审批</span>
          ) : (
            <span className="tag green">✓ 无待审批</span>
          )}
          <span className="tag">Demo 数据</span>
          <span>最近活动 {thread?.updatedAt ?? '刚刚'}</span>
        </div>
      </div>
      <Link className="pill-btn" to="/audit">
        查看审计 ↗
      </Link>
    </header>
  )
}

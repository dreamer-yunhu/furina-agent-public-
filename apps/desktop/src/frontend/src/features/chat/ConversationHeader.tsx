// ── AI-ASSISTED ── 本文件由 AI 生成/改写，待人工复核 ──
// 复核重点：
//   1. ★ 去掉了「Demo 数据 / 真实数据」标签和"无待审批"推断。
//      原因：删掉 demo 后只剩真实数据，标签没有意义；而"待审批"这个信息
//      后端列表接口并不返回，前端自己推不出来 —— 编一个就是假信息。
//   2. 只保留标题、线程 id 与审计入口。

import { Link } from '../../app/Link'

interface ConversationHeaderProps {
  title?: string
  threadId?: string
}

export function ConversationHeader({
  title,
  threadId,
}: ConversationHeaderProps) {
  return (
    <header className="chat-head">
      <div>
        <h1>{title ?? '新建会话'}</h1>
        <div className="subline">
          <span className="tag">线程 · {threadId ?? 'new-chat'}</span>
        </div>
      </div>
      <Link className="pill-btn" to="/audit">
        查看审计 ↗
      </Link>
    </header>
  )
}

// ── AI-ASSISTED ── 本文件由 AI 生成/改写，待人工复核 ──
// 复核重点：
//   1. ★ 删掉了工具调用行的渲染与 `getDemoApproval` 依赖。
//      原因：后端 `GET /threads/{id}/messages` 目前**不返回**每条消息的
//      工具调用与审批引用，前端拿不到这些数据。留着渲染分支只会产生
//      "永远不显示"的死代码，误导后来者以为已经接上了。
//      真正要做，得先在后端补 field —— 见 docs/PROGRESS.md 待办。
//   2. role === 'system' 用中性提示样式，不当成对话气泡。

import { artwork } from '../../assets/app/artwork'
import type { ViewMessage } from '../../types/view'

export function MessageRow({ message }: { message: ViewMessage }) {
  if (message.role === 'system') {
    return <div className="demo-note">ⓘ {message.content}</div>
  }

  if (message.role === 'user') {
    return (
      <div className="user-row">
        <div className="user-bubble">{message.content}</div>
      </div>
    )
  }

  return (
    <div className="msg">
      <div className="bot-avatar" aria-hidden="true">
        {artwork.avatar ? (
          <img className="bot-avatar__image" src={artwork.avatar} alt="" />
        ) : (
          '芙'
        )}
      </div>
      <div className="msg-body">
        <div className="msg-author">
          芙芙 Agent <span>{message.at}</span>
        </div>
        <div className="msg-text">{message.content}</div>
      </div>
    </div>
  )
}

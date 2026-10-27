// ── AI-ASSISTED ── 本文件由 AI 生成，待人工复核 ──
// 复核重点：消息结构对齐 Codex 原型（user-row / msg / tool-row），
// 工具调用状态与审批状态分开显示。

import { artwork } from '../../assets/app/artwork'
import { Icon } from '../../components/ui/Icon'
import type { DemoMessage, DemoToolCall } from '../../demo/types'
import { TOOL_STATUS_META } from '../shared/statusMeta'

function ToolCallRow({ call }: { call: DemoToolCall }) {
  const meta = TOOL_STATUS_META[call.status]
  const statusClass =
    call.status === 'pending'
      ? 'tool-status pending'
      : call.status === 'failed'
        ? 'tool-status failed'
        : 'tool-status'

  return (
    <div className="tool-row">
      <div className="tool-icon">
        <Icon name="terminal" size={13} />
      </div>
      <span className="mono">{call.name}</span>
      <span>{call.target}</span>
      <span className={statusClass}>
        {call.status === 'pending' ? '等待审批' : meta.label}
      </span>
    </div>
  )
}

export function MessageRow({ message }: { message: DemoMessage }) {
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
        {message.toolCalls?.length ? (
          <div>
            {message.toolCalls.map((call) => (
              <ToolCallRow key={call.id} call={call} />
            ))}
          </div>
        ) : null}
      </div>
    </div>
  )
}

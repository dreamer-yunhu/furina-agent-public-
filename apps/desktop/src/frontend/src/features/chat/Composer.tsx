// ── AI-ASSISTED ── 本文件由 AI 生成，待人工复核 ──
// 复核重点：发送只追加本地 Demo 消息，不调用后端；界面明确写清这一点。

import { useState } from 'react'

import { Icon } from '../../components/ui/Icon'

interface ComposerProps {
  onSend: (text: string) => void
}

export function Composer({ onSend }: ComposerProps) {
  const [value, setValue] = useState('')

  const submit = () => {
    const text = value.trim()
    if (!text) return
    onSend(text)
    setValue('')
  }

  return (
    <div className="composer">
      <textarea
        value={value}
        onChange={(event) => setValue(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === 'Enter' && !event.shiftKey) {
            event.preventDefault()
            submit()
          }
        }}
        placeholder="描述你希望 Agent 完成的任务…"
        aria-label="消息输入"
      />
      <div className="composer-bottom">
        <button
          type="button"
          className="pill-btn"
          title="附件（Demo 未实现）"
          aria-label="附件（Demo 未实现）"
          disabled
        >
          <Icon name="plus" size={13} />
        </button>
        <span>本地 Demo · Enter 发送，Shift + Enter 换行</span>
        <span className="spacer" />
        <button
          type="button"
          className="send"
          onClick={submit}
          disabled={!value.trim()}
        >
          发送 ↗
        </button>
      </div>
    </div>
  )
}

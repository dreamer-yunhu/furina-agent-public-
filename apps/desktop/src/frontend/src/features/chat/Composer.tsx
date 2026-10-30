// ── AI-ASSISTED ── 本文件由 AI 生成，待人工复核 ──
// 复核重点：Composer 只负责收集文本并回调；发不发后端由页面决定。
// `disabled` 用于流式进行中禁止重复提交（避免并发触发同一个 thread_busy）。

import { useState } from 'react'

import { Icon } from '../../components/ui/Icon'

interface ComposerProps {
  onSend: (text: string) => void
  disabled?: boolean
}

export function Composer({ onSend, disabled = false }: ComposerProps) {
  const [value, setValue] = useState('')

  const submit = () => {
    if (disabled) return
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
        <span>
          {disabled
            ? 'Agent 正在回复…'
            : 'Enter 发送，Shift + Enter 换行'}
        </span>
        <span className="spacer" />
        <button
          type="button"
          className="send"
          onClick={submit}
          disabled={disabled || !value.trim()}
        >
          发送 ↗
        </button>
      </div>
    </div>
  )
}

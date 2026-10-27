// ── AI-ASSISTED ── 本文件由 AI 生成，待人工复核 ──
// 复核重点：状态色只表达语气，不替代文本；标签样式与 Codex 原型保持一致。

import type { ReactNode } from 'react'

export type StatusTone =
  | 'neutral'
  | 'info'
  | 'success'
  | 'warning'
  | 'danger'
  | 'running'

const TONE_CLASS: Record<StatusTone, string> = {
  neutral: '',
  info: 'blue',
  success: 'green',
  warning: 'amber',
  danger: 'red',
  running: 'blue',
}

interface StatusPillProps {
  tone?: StatusTone
  children: ReactNode
  dot?: boolean
  title?: string
}

export function StatusPill({
  tone = 'neutral',
  children,
  dot = false,
  title,
}: StatusPillProps) {
  const toneClass = TONE_CLASS[tone]
  return (
    <span className={toneClass ? `tag ${toneClass}` : 'tag'} title={title}>
      {dot ? <span className="dot" aria-hidden="true" /> : null}
      {children}
    </span>
  )
}

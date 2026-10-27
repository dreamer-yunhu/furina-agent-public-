// ── AI-ASSISTED ── 本文件由 AI 生成，待人工复核 ──

import type { ReactNode } from 'react'

type NoticeTone = 'info' | 'warning'

interface NoticeProps {
  tone?: NoticeTone
  title: string
  children: ReactNode
}

export function Notice({ tone = 'info', title, children }: NoticeProps) {
  return (
    <div className={`notice notice--${tone}`}>
      <strong className="notice__title">{title}</strong>
      <div className="notice__body">{children}</div>
    </div>
  )
}

// ── AI-ASSISTED ── 本文件由 AI 生成，待人工复核 ──

import type { ReactNode } from 'react'

interface ContentSectionProps {
  title: string
  description?: string
  actions?: ReactNode
  children: ReactNode
}

export function ContentSection({
  title,
  description,
  actions,
  children,
}: ContentSectionProps) {
  return (
    <section className="thread-card">
      <div className="thread-card-head">
        <div className="thread-card-info">
          <b>{title}</b>
          {description ? <small>{description}</small> : null}
        </div>
        {actions ? <div className="right">{actions}</div> : null}
      </div>
      <div className="section-card__body">{children}</div>
    </section>
  )
}

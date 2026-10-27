// ── AI-ASSISTED ── 本文件由 AI 生成，待人工复核 ──

import type { ReactNode } from 'react'

interface PageHeaderProps {
  title: string
  description?: string
  meta?: ReactNode
  actions?: ReactNode
}

export function PageHeader({ title, description, meta, actions }: PageHeaderProps) {
  return (
    <header className="page-title">
      <h1>{title}</h1>
      {description ? <p>{description}</p> : null}
      {meta ? <div className="page-title-meta">{meta}</div> : null}
      {actions ? <div className="page-title-actions">{actions}</div> : null}
    </header>
  )
}

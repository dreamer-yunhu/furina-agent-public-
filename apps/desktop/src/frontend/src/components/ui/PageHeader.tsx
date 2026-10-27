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
    <header className="page-header">
      <div className="page-header__text">
        <h1 className="page-header__title">{title}</h1>
        {description ? <p className="page-header__description">{description}</p> : null}
        {meta ? <div className="page-header__meta">{meta}</div> : null}
      </div>
      {actions ? <div className="page-header__actions">{actions}</div> : null}
    </header>
  )
}

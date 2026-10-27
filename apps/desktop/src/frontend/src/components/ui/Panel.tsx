// ── AI-ASSISTED ── 本文件由 AI 生成，待人工复核 ──

import type { ReactNode } from 'react'

interface PanelProps {
  title: string
  description?: string
  actions?: ReactNode
  children: ReactNode
  className?: string
}

export function Panel({ title, description, actions, children, className }: PanelProps) {
  return (
    <section className={className ? `panel ${className}` : 'panel'}>
      <header className="panel__header">
        <div className="panel__heading">
          <h2 className="panel__title">{title}</h2>
          {description ? <p className="panel__description">{description}</p> : null}
        </div>
        {actions ? <div className="panel__actions">{actions}</div> : null}
      </header>
      <div className="panel__body">{children}</div>
    </section>
  )
}

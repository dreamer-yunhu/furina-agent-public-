// ── AI-ASSISTED ── 本文件由 AI 生成，待人工复核 ──
// 复核重点：文案必须明确「尚未接入」；有美术资源时用插图，没有时回退到中性占位。

import { artwork } from '../../assets/app/artwork'

interface EmptyStateProps {
  title: string
  description: string
  hint?: string
}

export function EmptyState({ title, description, hint }: EmptyStateProps) {
  return (
    <div className="empty-state">
      {artwork.emptyState ? (
        <img className="empty-state__image" src={artwork.emptyState} alt="" />
      ) : (
        <div className="empty-state__mark" aria-hidden="true" />
      )}
      <h3 className="empty-state__title">{title}</h3>
      <p className="empty-state__description">{description}</p>
      {hint ? <p className="empty-state__hint">{hint}</p> : null}
    </div>
  )
}

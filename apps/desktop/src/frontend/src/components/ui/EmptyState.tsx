// ── AI-ASSISTED ── 本文件由 AI 生成，待人工复核 ──
// 复核重点：这里的文案必须明确「尚未接入」，不能让人误以为已有真实数据。

interface EmptyStateProps {
  title: string
  description: string
  hint?: string
}

export function EmptyState({ title, description, hint }: EmptyStateProps) {
  return (
    <div className="empty-state">
      <div className="empty-state__mark" aria-hidden="true" />
      <h3 className="empty-state__title">{title}</h3>
      <p className="empty-state__description">{description}</p>
      {hint ? <p className="empty-state__hint">{hint}</p> : null}
    </div>
  )
}

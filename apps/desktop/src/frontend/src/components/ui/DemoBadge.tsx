// ── AI-ASSISTED ── 本文件由 AI 生成，待人工复核 ──

interface DemoBadgeProps {
  label?: string
}

export function DemoBadge({ label = 'Demo 数据' }: DemoBadgeProps) {
  return (
    <span
      className="tag"
      title="演示数据，不代表真实后端状态，也不会触发真实执行"
    >
      {label}
    </span>
  )
}

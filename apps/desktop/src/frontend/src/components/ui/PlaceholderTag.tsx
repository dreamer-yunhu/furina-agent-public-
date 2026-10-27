// ── AI-ASSISTED ── 本文件由 AI 生成，待人工复核 ──

interface PlaceholderTagProps {
  label?: string
}

export function PlaceholderTag({ label = '占位' }: PlaceholderTagProps) {
  return <span className="tag tag--placeholder">{label}</span>
}

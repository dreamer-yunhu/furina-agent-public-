// ── AI-ASSISTED ── 本文件由 AI 生成，待人工复核 ──

import type { ReactNode } from 'react'

export interface KeyValueItem {
  label: string
  value: ReactNode
  note?: string
}

interface KeyValueListProps {
  items: KeyValueItem[]
}

export function KeyValueList({ items }: KeyValueListProps) {
  return (
    <div className="kv-list">
      {items.map((item) => (
        <div className="field" key={item.label}>
          <span className="label">{item.label}</span>
          <div>
            {item.value}
            {item.note ? <small className="muted"> {item.note}</small> : null}
          </div>
        </div>
      ))}
    </div>
  )
}

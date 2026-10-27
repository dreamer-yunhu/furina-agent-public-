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
    <dl className="key-value">
      {items.map((item) => (
        <div className="key-value__row" key={item.label}>
          <dt className="key-value__label">{item.label}</dt>
          <dd className="key-value__value">
            {item.value}
            {item.note ? <span className="key-value__note">{item.note}</span> : null}
          </dd>
        </div>
      ))}
    </dl>
  )
}

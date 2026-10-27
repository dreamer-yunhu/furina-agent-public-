// ── AI-ASSISTED ── 本文件由 AI 生成，待人工复核 ──

import type { ReactNode } from 'react'

export function InspectorSlot({ children }: { children: ReactNode }) {
  return (
    <aside className="slot slot--inspector" aria-label="详情面板">
      {children}
    </aside>
  )
}

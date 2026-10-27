// ── AI-ASSISTED ── 本文件由 AI 生成，待人工复核 ──
// 复核重点：背景层永远在内容下方，且不接收指针事件。

import type { ReactNode } from 'react'

export function BackgroundSlot({ children }: { children?: ReactNode }) {
  return (
    <div className="slot slot--background" aria-hidden="true">
      {children}
    </div>
  )
}

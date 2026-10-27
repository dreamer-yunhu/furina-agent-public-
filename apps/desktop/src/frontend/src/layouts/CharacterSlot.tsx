// ── AI-ASSISTED ── 本文件由 AI 生成，待人工复核 ──
// 复核重点：当前只是工作台内的角色占位；独立角色窗口属于 F4，
// 不要把窗口生命周期、Live2D 或任务状态塞进这个组件。

import type { ReactNode } from 'react'

export function CharacterSlot({ children }: { children?: ReactNode }) {
  return (
    <aside className="slot slot--character" aria-label="角色窗口占位">
      {children}
    </aside>
  )
}

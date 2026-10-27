// ── AI-ASSISTED ── 本文件由 AI 生成，待人工复核 ──
// 复核重点：关闭按钮只影响布局，不代表取消任务或审批。

import type { ReactNode } from 'react'

interface InspectorSlotProps {
  children?: ReactNode
  onClose?: () => void
}

export function InspectorSlot({ children, onClose }: InspectorSlotProps) {
  return (
    <aside className="slot slot--inspector" aria-label="详情面板">
      <div className="panel-head">
        <h3>当前任务详情</h3>
        {onClose ? (
          <button type="button" className="pill-btn" onClick={onClose}>
            关闭
          </button>
        ) : null}
      </div>
      <div className="panel-content">{children}</div>
    </aside>
  )
}

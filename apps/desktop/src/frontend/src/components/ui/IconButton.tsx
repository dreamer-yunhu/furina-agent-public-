// ── AI-ASSISTED ── 本文件由 AI 生成，待人工复核 ──
// 复核重点：图标按钮必须有 aria-label / title；不要用纯图标表达唯一语义。

import type { ButtonHTMLAttributes, ReactNode } from 'react'

interface IconButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  label: string
  active?: boolean
  children: ReactNode
}

export function IconButton({
  label,
  active = false,
  children,
  className,
  ...rest
}: IconButtonProps) {
  return (
    <button
      type="button"
      className={className ? `icon-button ${className}` : 'icon-button'}
      aria-label={label}
      title={label}
      data-active={active ? 'true' : undefined}
      {...rest}
    >
      {children}
    </button>
  )
}

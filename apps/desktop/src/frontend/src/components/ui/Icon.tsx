// ── AI-ASSISTED ── 本文件由 AI 生成，待人工复核 ──
// 复核重点：内联 SVG，不引入图标库；新增图标只在这里加 path。

import type { ReactNode } from 'react'

export type IconName =
  | 'panel-left'
  | 'panel-right'
  | 'plus'
  | 'chevron-right'
  | 'chevron-down'
  | 'check'
  | 'x'
  | 'clock'
  | 'alert'
  | 'search'
  | 'file'
  | 'terminal'
  | 'message'
  | 'list'
  | 'shield'
  | 'sliders'
  | 'sun'
  | 'moon'
  | 'monitor'

const PATHS: Record<IconName, ReactNode> = {
  'panel-left': (
    <>
      <rect x="2" y="2.5" width="12" height="11" rx="1.5" />
      <path d="M6 2.5v11" />
    </>
  ),
  'panel-right': (
    <>
      <rect x="2" y="2.5" width="12" height="11" rx="1.5" />
      <path d="M10 2.5v11" />
    </>
  ),
  plus: <path d="M8 3v10M3 8h10" />,
  'chevron-right': <path d="M6 3l4 5-4 5" />,
  'chevron-down': <path d="M3 6l5 4 5-4" />,
  check: <path d="M3 8.5l3 3 7-7" />,
  x: <path d="M4 4l8 8M12 4l-8 8" />,
  clock: (
    <>
      <circle cx="8" cy="8" r="5.5" />
      <path d="M8 5v3.5l2 1" />
    </>
  ),
  alert: (
    <>
      <path d="M8 2.5l6 10.5H2L8 2.5z" />
      <path d="M8 6v3M8 11.2v.1" />
    </>
  ),
  search: (
    <>
      <circle cx="7" cy="7" r="4.5" />
      <path d="M10.5 10.5l3 3" />
    </>
  ),
  file: (
    <>
      <path d="M4 2.5h5l3 3v8H4z" />
      <path d="M9 2.5v3h3" />
    </>
  ),
  terminal: (
    <>
      <rect x="2" y="3" width="12" height="10" rx="1.5" />
      <path d="M4.5 6.5l2 1.5-2 1.5M8.5 10h3" />
    </>
  ),
  message: (
    <>
      <path d="M2.5 3.5h11v7h-6l-3 3v-3h-2z" />
    </>
  ),
  list: (
    <>
      <path d="M6 4h8M6 8h8M6 12h8" />
      <path d="M3 4h.1M3 8h.1M3 12h.1" />
    </>
  ),
  shield: (
    <>
      <path d="M8 2l5 2v4c0 3-2 5-5 6-3-1-5-3-5-6V4l5-2z" />
      <path d="M6 8l1.5 1.5L10.5 6.5" />
    </>
  ),
  sliders: (
    <>
      <path d="M3 5h10M3 11h10" />
      <circle cx="6" cy="5" r="1.4" />
      <circle cx="10" cy="11" r="1.4" />
    </>
  ),
  sun: (
    <>
      <circle cx="8" cy="8" r="3" />
      <path d="M8 1.5v1.5M8 13v1.5M1.5 8H3M13 8h1.5M3.4 3.4l1 1M11.6 11.6l1 1M12.6 3.4l-1 1M4.4 11.6l-1 1" />
    </>
  ),
  moon: <path d="M12.5 9.5A5.5 5.5 0 015.8 3a5.5 5.5 0 106.7 6.5z" />,
  monitor: (
    <>
      <rect x="2" y="3" width="12" height="8" rx="1.2" />
      <path d="M6 13.5h4M8 11v2.5" />
    </>
  ),
}

interface IconProps {
  name: IconName
  size?: number
  className?: string
}

export function Icon({ name, size = 16, className }: IconProps) {
  return (
    <svg
      className={className}
      width={size}
      height={size}
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.4"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {PATHS[name]}
    </svg>
  )
}

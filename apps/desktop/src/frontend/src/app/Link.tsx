// ── AI-ASSISTED ── 本文件由 AI 生成，待人工复核 ──
// 复核重点：只拦截普通左键点击；带修饰键/中键的点击交给浏览器默认行为。

import type { AnchorHTMLAttributes, MouseEvent, ReactNode } from 'react'

import { navigate } from './router'

interface LinkProps extends Omit<AnchorHTMLAttributes<HTMLAnchorElement>, 'href'> {
  to: string
  children: ReactNode
}

export function Link({ to, children, onClick, ...rest }: LinkProps) {
  const handleClick = (event: MouseEvent<HTMLAnchorElement>) => {
    onClick?.(event)
    if (event.defaultPrevented) return

    if (
      event.button !== 0 ||
      event.metaKey ||
      event.ctrlKey ||
      event.shiftKey ||
      event.altKey
    ) {
      return
    }

    event.preventDefault()
    navigate(to)
  }

  return (
    <a href={`#${to}`} onClick={handleClick} {...rest}>
      {children}
    </a>
  )
}

// ── AI-ASSISTED ── 本文件由 AI 生成，待人工复核 ──
// 复核重点：主题必须只有一份状态；顶栏按钮与设置页共用同一个 context。

import type { ReactNode } from 'react'

import { useTheme } from '../../hooks/useTheme'
import { ThemeContext } from './themeContext'

export function ThemeProvider({ children }: { children: ReactNode }) {
  const value = useTheme()
  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>
}

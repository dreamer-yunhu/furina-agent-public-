// ── AI-ASSISTED ── 本文件由 AI 生成，待人工复核 ──
// 复核重点：context 与 hook 单独放，避免 ThemeProvider.tsx 同时导出组件和函数
// 触发 react-refresh 的 only-export-components 警告。

import { createContext, useContext } from 'react'

import type { ThemeMode } from '../../hooks/useTheme'

export interface ThemeContextValue {
  mode: ThemeMode
  setMode: (mode: ThemeMode) => void
  cycle: () => void
}

export const ThemeContext = createContext<ThemeContextValue | null>(null)

export function useThemeContext(): ThemeContextValue {
  const value = useContext(ThemeContext)
  if (!value) {
    throw new Error('useThemeContext 必须在 ThemeProvider 内使用')
  }
  return value
}

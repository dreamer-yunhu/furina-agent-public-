// ── AI-ASSISTED ── 本文件由 AI 生成，待人工复核 ──
// 复核重点：
//   1. `system` 时不写 data-theme，让 theme.css 的 prefers-color-scheme 生效。
//   2. localStorage 读写都可能抛异常（隐私模式），必须吞掉，不能阻断渲染。
//   3. 这是一个 UI 层 hook，不涉及任何业务状态。

import { useEffect, useState } from 'react'

export type ThemeMode = 'system' | 'light' | 'dark'

const STORAGE_KEY = 'furina.theme'
const ORDER: ThemeMode[] = ['system', 'light', 'dark']

export const THEME_LABELS: Record<ThemeMode, string> = {
  system: '跟随系统',
  light: '浅色',
  dark: '深色',
}

function readTheme(): ThemeMode {
  try {
    const stored = window.localStorage.getItem(STORAGE_KEY)
    if (stored === 'light' || stored === 'dark' || stored === 'system') {
      return stored
    }
    return 'light'
  } catch {
    return 'light'
  }
}

function applyTheme(mode: ThemeMode): void {
  const root = document.documentElement
  if (mode === 'system') {
    root.removeAttribute('data-theme')
  } else {
    root.dataset.theme = mode
  }
}

export function useTheme() {
  const [mode, setMode] = useState<ThemeMode>(readTheme)

  useEffect(() => {
    applyTheme(mode)
    try {
      window.localStorage.setItem(STORAGE_KEY, mode)
    } catch {
      // 隐私模式 / 存储被禁用时忽略即可
    }
  }, [mode])

  const cycle = () => {
    setMode((current) => ORDER[(ORDER.indexOf(current) + 1) % ORDER.length])
  }

  return { mode, setMode, cycle }
}

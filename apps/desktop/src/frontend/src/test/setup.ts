// ── AI-ASSISTED ── 本文件由 AI 生成，待人工复核 ──

import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach } from 'vitest'

afterEach(() => {
  cleanup()
  document.documentElement.removeAttribute('data-theme')
  window.localStorage.clear()
})

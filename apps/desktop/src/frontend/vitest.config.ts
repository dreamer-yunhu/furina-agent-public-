// ── AI-ASSISTED ── 本文件由 AI 生成，待人工复核 ──
// 复核重点：测试只跑纯前端（jsdom），不启动后端、不访问网络。

import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
  },
})

// ── AI-ASSISTED ── 本文件由 AI 生成，待人工复核 ──
// 复核重点：样式入口只有一个；不要在组件里散落全局 CSS 导入。

import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

import { App } from './app/App'
import './styles/index.css'

const container = document.getElementById('root')

if (!container) {
  throw new Error('找不到 #root 挂载点')
}

createRoot(container).render(
  <StrictMode>
    <App />
  </StrictMode>,
)

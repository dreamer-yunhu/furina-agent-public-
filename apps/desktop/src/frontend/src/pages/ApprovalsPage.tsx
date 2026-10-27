// ── AI-ASSISTED ── 本文件由 AI 生成，待人工复核 ──
// 旧入口保留路由，统一跳到新的审计页，避免两套审批 UI 漂移。

import { useEffect } from 'react'

import { navigate } from '../app/router'

export function ApprovalsPage() {
  useEffect(() => {
    navigate('/audit', { replace: true })
  }, [])

  return null
}

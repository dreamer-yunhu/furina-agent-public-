// ── AI-ASSISTED ── 本文件由 AI 生成，待人工复核 ──
// 旧入口保留路由，统一跳到新的审计页；审批详情见 /audit/:threadId/:approvalId。

import { useEffect } from 'react'

import { navigate } from '../app/router'

interface ApprovalDetailPageProps {
  approvalRequestId: string
}

export function ApprovalDetailPage(_props: ApprovalDetailPageProps) {
  useEffect(() => {
    navigate('/audit', { replace: true })
  }, [])

  return null
}

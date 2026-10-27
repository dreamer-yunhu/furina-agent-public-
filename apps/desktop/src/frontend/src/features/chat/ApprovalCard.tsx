// ── AI-ASSISTED ── 本文件由 AI 生成，待人工复核 ──
// 复核重点：
//   1. 审批状态与工具执行状态是两套字段；「已批准」绝不能显示成「执行成功」。
//   2. 批准/拒绝只改本地状态，并明确标注 Demo，不调用任何接口。
//   3. 待审批卡片醒目；已处理卡片默认折叠，可重新展开。

import { useState } from 'react'

import type {
  DemoApproval,
  DemoApprovalStatus,
  DemoToolStatus,
} from '../../demo/types'
import {
  APPROVAL_STATUS_META,
  RISK_META,
  TOOL_STATUS_META,
} from '../shared/statusMeta'

const RISK_CLASS: Record<string, string> = {
  low: 'risk low',
  medium: 'risk medium',
  high: 'risk',
}

interface ApprovalCardProps {
  approval: DemoApproval
}

export function ApprovalCard({ approval }: ApprovalCardProps) {
  const [status, setStatus] = useState<DemoApprovalStatus>(approval.status)
  const [expanded, setExpanded] = useState(false)
  const [locallyDecided, setLocallyDecided] = useState(false)
  const [localReason, setLocalReason] = useState<string | undefined>()

  const approvalMeta = APPROVAL_STATUS_META[status]
  const riskMeta = RISK_META[approval.risk]
  const toolStatus: DemoToolStatus = locallyDecided
    ? status === 'approved'
      ? 'pending'
      : 'skipped'
    : approval.toolExecutionStatus
  const toolMeta = TOOL_STATUS_META[toolStatus]

  const decide = (next: 'approved' | 'rejected') => {
    setStatus(next)
    setExpanded(false)
    setLocallyDecided(true)
    setLocalReason(next === 'rejected' ? '用户拒绝（Demo）' : undefined)
  }

  if (status === 'pending') {
    return (
      <div className="approval">
        <div className="approval-top">
          <span className="tag amber">● 待审批</span>
          <strong className="mono">{approval.toolName}</strong>
          <span className={RISK_CLASS[approval.risk]}>{riskMeta.label}</span>
          <span className="tag">Demo 数据</span>
          <span className="right">{approval.requestedAt}</span>
        </div>
        <div className="approval-body">
          <div className="target-line">
            <span className="label">目标资源</span>
            <span className="target">{approval.target}</span>
          </div>
          <div className="summary">{approval.summary}</div>
          <div className="warning">
            ⚠ 批准仅授权本次请求中的工具与参数，不代表执行成功，也不会授权后续操作。
          </div>
        </div>
        <div className="approval-actions">
          <button
            type="button"
            className="btn"
            onClick={() => decide('rejected')}
          >
            拒绝
          </button>
          <button
            type="button"
            className="btn primary"
            onClick={() => decide('approved')}
          >
            批准执行
          </button>
        </div>
      </div>
    )
  }

  const decidedAt = locallyDecided ? '刚刚' : approval.decidedAt
  const decidedBy = locallyDecided ? '本地用户（Demo）' : approval.decidedBy
  const reason = localReason ?? approval.decisionReason
  const summaryRight = locallyDecided
    ? status === 'approved'
      ? '未执行 · 等待真实结果'
      : '工具未执行'
    : `${decidedAt ?? approval.requestedAt} · ${toolMeta.label}`

  return (
    <div
      className={`approval approval--${
        status === 'approved' ? 'approved' : 'rejected'
      }`}
    >
      <button
        type="button"
        className="collapsed-summary"
        aria-expanded={expanded}
        onClick={() => setExpanded((current) => !current)}
      >
        <span className={`tag ${status === 'approved' ? 'green' : 'amber'}`}>
          {status === 'approved' ? '✓ 已批准' : '↗ 已拒绝'}
        </span>
        <strong className="mono">{approval.toolName}</strong>
        <small>{approval.target}</small>
        <span className="right">{summaryRight}</span>
        <span aria-hidden="true">⌄</span>
      </button>

      {expanded ? (
        <div className="approval-body">
          <div className="summary">{approval.summary}</div>
          <div className="kv-list">
            <div className="field">
              <span className="label">审批决定</span>
              <div>
                {approvalMeta.label}
                {decidedAt ? ` · ${decidedAt}` : null}
                {decidedBy ? ` · ${decidedBy}` : null}
                {reason ? ` · ${reason}` : null}
              </div>
            </div>
            <div className="field">
              <span className="label">工具执行</span>
              <div>
                {toolMeta.label}
                {locallyDecided
                  ? ' · 本地 Demo 不会真正执行'
                  : approval.toolResult
                    ? ` · ${approval.toolResult}`
                    : null}
              </div>
            </div>
            <div className="field">
              <span className="label">执行 ID</span>
              <div>
                <code>{approval.executionId}</code>
              </div>
            </div>
          </div>
          <div className="warning">
            审批决策与工具执行结果是不同状态；本卡片为 Demo，不会调用后端。
          </div>
        </div>
      ) : null}
    </div>
  )
}

// ── AI-ASSISTED ── 本文件由 AI 生成，待人工复核 ──
// 复核重点：只验证 Demo 卡片交互；不涉及任何后端调用或真实审批。

import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { demoApprovals } from '../../demo/data'
import { ApprovalCard } from './ApprovalCard'

const pending = demoApprovals.find((approval) => approval.status === 'pending')

if (!pending) {
  throw new Error('Demo 数据缺少 pending 审批，测试夹具失效')
}

describe('ApprovalCard', () => {
  it('approves locally and collapses to a summary', () => {
    render(<ApprovalCard approval={pending} />)

    expect(screen.getByText('● 待审批')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '批准执行' }))

    expect(screen.getByText('✓ 已批准')).toBeInTheDocument()
    expect(screen.queryByText('● 待审批')).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /已批准/ }))
    expect(screen.getByText(/等待执行/)).toBeInTheDocument()
    expect(
      screen.getByText(/本地 Demo 不会真正执行/),
    ).toBeInTheDocument()
  })

  it('rejects locally and marks the tool as not executed', () => {
    render(<ApprovalCard approval={pending} />)

    fireEvent.click(screen.getByRole('button', { name: '拒绝' }))

    expect(screen.getByText('↗ 已拒绝')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /已拒绝/ }))

    expect(screen.getByText(/^未执行/)).toBeInTheDocument()
    expect(screen.getByText(/用户拒绝（Demo）/)).toBeInTheDocument()
  })
})

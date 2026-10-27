// ── AI-ASSISTED ── 本文件由 AI 生成，待人工复核 ──
// 复核重点：证明插槽内容完全由 props 注入 —— 换美术组件不需要改布局。

import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { WorkbenchLayout } from './WorkbenchLayout'

function renderLayout(inspectorOpen: boolean) {
  return render(
    <WorkbenchLayout
      header={<span>HEADER-SLOT</span>}
      sidebar={<span>SIDEBAR-SLOT</span>}
      inspector={<span>INSPECTOR-SLOT</span>}
      inspectorOpen={inspectorOpen}
      background={<span>BACKGROUND-SLOT</span>}
      character={<span>CHARACTER-SLOT</span>}
    >
      <span>MAIN-SLOT</span>
    </WorkbenchLayout>,
  )
}

describe('WorkbenchLayout', () => {
  it('renders every slot from props', () => {
    const { container } = renderLayout(true)

    expect(screen.getByText('HEADER-SLOT')).toBeInTheDocument()
    expect(screen.getByText('SIDEBAR-SLOT')).toBeInTheDocument()
    expect(screen.getByText('MAIN-SLOT')).toBeInTheDocument()
    expect(screen.getByText('INSPECTOR-SLOT')).toBeInTheDocument()
    expect(screen.getByText('BACKGROUND-SLOT')).toBeInTheDocument()
    expect(screen.getByText('CHARACTER-SLOT')).toBeInTheDocument()
    expect(container.querySelector('.workbench')).toHaveAttribute(
      'data-inspector',
      'open',
    )
  })

  it('does not render the inspector when closed', () => {
    const { container } = renderLayout(false)

    expect(screen.queryByText('INSPECTOR-SLOT')).not.toBeInTheDocument()
    expect(container.querySelector('.workbench')).toHaveAttribute(
      'data-inspector',
      'closed',
    )
  })
})

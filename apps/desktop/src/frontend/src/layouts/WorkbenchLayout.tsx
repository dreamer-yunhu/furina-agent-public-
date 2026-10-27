// ── AI-ASSISTED ── 本文件由 AI 生成，待人工复核 ──
// 复核重点：
//   1. 布局只负责尺寸、定位、滚动区域；不读取任何业务状态。
//   2. 插槽全部通过 props 注入 —— 换美术时只替换插槽内容，不改本文件。
//   3. Inspector 是否占列由 `inspectorOpen` 决定，窄屏下由 CSS 改成浮层。

import type { ReactNode } from 'react'

import { BackgroundSlot } from './BackgroundSlot'
import { CharacterSlot } from './CharacterSlot'
import { HeaderSlot } from './HeaderSlot'
import { InspectorSlot } from './InspectorSlot'
import { MainWorkspaceSlot } from './MainWorkspaceSlot'
import { SidebarSlot } from './SidebarSlot'

interface WorkbenchLayoutProps {
  header: ReactNode
  sidebar: ReactNode
  children: ReactNode
  inspector?: ReactNode
  inspectorOpen?: boolean
  background?: ReactNode
  character?: ReactNode
}

export function WorkbenchLayout({
  header,
  sidebar,
  children,
  inspector,
  inspectorOpen = false,
  background,
  character,
}: WorkbenchLayoutProps) {
  return (
    <div className="workbench" data-inspector={inspectorOpen ? 'open' : 'closed'}>
      <BackgroundSlot>{background}</BackgroundSlot>
      <CharacterSlot>{character}</CharacterSlot>
      <HeaderSlot>{header}</HeaderSlot>
      <SidebarSlot>{sidebar}</SidebarSlot>
      <MainWorkspaceSlot>{children}</MainWorkspaceSlot>
      {inspectorOpen ? <InspectorSlot>{inspector}</InspectorSlot> : null}
    </div>
  )
}

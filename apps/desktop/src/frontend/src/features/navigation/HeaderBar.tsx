// ── AI-ASSISTED ── 本文件由 AI 生成，待人工复核 ──
// 复核重点：顶栏按 Codex 原型使用「面包屑 + 演示环境 + 详情面板 + 主题」，
// 不显示真实连接状态；F2 之前不要伪装后端在线。

import { Icon } from '../../components/ui/Icon'
import type { IconName } from '../../components/ui/Icon'
import { IconButton } from '../../components/ui/IconButton'
import { THEME_LABELS, type ThemeMode } from '../../hooks/useTheme'

const THEME_ICONS: Record<ThemeMode, IconName> = {
  system: 'monitor',
  light: 'sun',
  dark: 'moon',
}

interface HeaderBarProps {
  title: string
  sidebarCollapsed: boolean
  onToggleSidebar: () => void
  inspectorAvailable: boolean
  inspectorOpen: boolean
  onToggleInspector: () => void
  themeMode: ThemeMode
  onCycleTheme: () => void
}

export function HeaderBar({
  title,
  sidebarCollapsed,
  onToggleSidebar,
  inspectorAvailable,
  inspectorOpen,
  onToggleInspector,
  themeMode,
  onCycleTheme,
}: HeaderBarProps) {
  return (
    <div className="header-bar">
      <div className="topbar-left">
        <IconButton
          label={sidebarCollapsed ? '展开侧栏' : '收起侧栏'}
          onClick={onToggleSidebar}
        >
          <Icon name="panel-left" size={15} />
        </IconButton>
        <div className="crumb">
          <strong>芙芙 Agent</strong>
          <span aria-hidden="true">/</span>
          <span>{title}</span>
        </div>
      </div>

      <div className="top-actions">
        <div className="status">
          <span className="dot green" aria-hidden="true" />
          演示环境
        </div>
        {inspectorAvailable ? (
          <button
            type="button"
            className="pill-btn"
            onClick={onToggleInspector}
            aria-pressed={inspectorOpen}
          >
            {inspectorOpen ? '收起详情' : '详情面板'}
          </button>
        ) : null}
        <button
          type="button"
          className="pill-btn"
          onClick={onCycleTheme}
          aria-label={`切换主题（当前：${THEME_LABELS[themeMode]}）`}
          title={`切换主题（当前：${THEME_LABELS[themeMode]}）`}
        >
          <Icon name={THEME_ICONS[themeMode]} size={14} />
        </button>
      </div>
    </div>
  )
}

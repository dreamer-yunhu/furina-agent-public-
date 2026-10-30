// ── AI-ASSISTED ── 本文件由 AI 生成，待人工复核 ──
// 复核重点：
//   1. 连接状态由 BackendProvider 真实探测得出，顶栏**不再写死「演示环境」**。
//   2. 默认值是 unknown（「连接待检测」），不是 online —— 没探完就不能显示已连接。

import {
  ConnectionStatus,
  type ConnectionState,
} from '../../components/feedback/ConnectionStatus'
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
  /** 本地后端连接状态；未传时按 unknown 处理，不假设在线 */
  connection?: ConnectionState
  connectionDetail?: string
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
  connection = 'unknown',
  connectionDetail,
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
        <ConnectionStatus state={connection} detail={connectionDetail} />
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

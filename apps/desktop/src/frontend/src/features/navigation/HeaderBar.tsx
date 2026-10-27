// ── AI-ASSISTED ── 本文件由 AI 生成，待人工复核 ──
// 复核重点：标题来自路由表，不在这里维护第二份映射。

import { ConnectionStatus } from '../../components/feedback/ConnectionStatus'
import { windowRoleLabel, type WindowRole } from '../../services/desktop/windowRoles'

interface HeaderBarProps {
  title: string
  windowRole: WindowRole
}

export function HeaderBar({ title, windowRole }: HeaderBarProps) {
  return (
    <div className="header-bar">
      <div className="header-bar__identity">
        <span className="header-bar__brand">芙宁娜</span>
        <span className="header-bar__divider" aria-hidden="true">
          /
        </span>
        <span className="header-bar__title">{title}</span>
      </div>
      <div className="header-bar__meta">
        <span className="header-bar__role">{windowRoleLabel(windowRole)}</span>
        <ConnectionStatus />
      </div>
    </div>
  )
}

// ── AI-ASSISTED ── 本文件由 AI 生成，待人工复核 ──
// 复核重点：这是 F4 双窗口的适配缝，当前**没有接线到 Tauri**。
// 现在只根据 URL 查询参数识别角色，方便将来同一份前端同时服务两个窗口；
// 不要在这里偷偷创建窗口或管理 Python 进程。

export const WINDOW_ROLES = ['workbench', 'character'] as const

export type WindowRole = (typeof WINDOW_ROLES)[number]

const ROLE_LABELS: Record<WindowRole, string> = {
  workbench: '工作台窗口',
  character: '角色窗口',
}

export function resolveWindowRole(search?: string): WindowRole {
  const query = search ?? window.location.search
  return new URLSearchParams(query).get('window') === 'character'
    ? 'character'
    : 'workbench'
}

export function windowRoleLabel(role: WindowRole): string {
  return ROLE_LABELS[role]
}

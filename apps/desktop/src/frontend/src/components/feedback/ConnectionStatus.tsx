// ── AI-ASSISTED ── 本文件由 AI 生成，待人工复核 ──
// 复核重点：F1 不发起任何网络请求；默认状态必须是 unknown，
// 不要为了"好看"默认显示已连接。

export type ConnectionState = 'unknown' | 'online' | 'offline'

const LABELS: Record<ConnectionState, string> = {
  unknown: '连接待检测',
  online: '已连接',
  offline: '未连接',
}

interface ConnectionStatusProps {
  state?: ConnectionState
  detail?: string
}

export function ConnectionStatus({
  state = 'unknown',
  detail = 'F2 接入真实健康检查（GET /healthz）',
}: ConnectionStatusProps) {
  return (
    <span className={`connection connection--${state}`} title={detail}>
      <span className="connection__dot" aria-hidden="true" />
      {LABELS[state]}
    </span>
  )
}

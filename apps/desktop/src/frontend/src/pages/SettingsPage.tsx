// ── AI-ASSISTED ── 本文件由 AI 生成，待人工复核 ──
// 复核重点：F1 不发起探活请求；连接状态固定为 unknown。

import { ConnectionStatus } from '../components/feedback/ConnectionStatus'
import { KeyValueList } from '../components/ui/KeyValueList'
import { Notice } from '../components/ui/Notice'
import { PageHeader } from '../components/ui/PageHeader'
import { Panel } from '../components/ui/Panel'
import { API_BASE_URL } from '../services/api/config'

export function SettingsPage() {
  return (
    <div className="page">
      <PageHeader
        title="设置"
        description="F1 只展示静态环境信息，不实现配置中心。"
      />

      <Panel title="后端连接">
        <KeyValueList
          items={[
            { label: 'API 基址', value: <code>{API_BASE_URL}</code> },
            { label: '连接状态', value: <ConnectionStatus /> },
            { label: '健康检查', value: <code>GET /healthz</code> },
          ]}
        />
        <Notice tone="info" title="F2 接入">
          真实探活、超时与错误提示在 F2 实现。当前页面不会发起任何网络请求。
        </Notice>
      </Panel>

      <Panel title="界面主题">
        <p className="muted">
          主题由 <code>src/styles/tokens.css</code> 与 <code>theme.css</code> 控制。
          替换颜色、间距、圆角与字体不需要改业务组件；替换美术资源请使用
          <code>src/assets/app/artwork.ts</code>。
        </p>
      </Panel>

      <Panel title="关于">
        <KeyValueList
          items={[
            { label: '阶段', value: 'F1 · 工作台骨架与美术插槽' },
            { label: '前端版本', value: '0.0.0' },
            { label: '后端', value: 'FastAPI · 127.0.0.1:8001' },
            { label: '桌面壳', value: 'Tauri 2（F1 未托管 Python）' },
          ]}
        />
      </Panel>
    </div>
  )
}

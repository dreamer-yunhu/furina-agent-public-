// ── AI-ASSISTED ── 本文件由 AI 生成，待人工复核 ──
// 复核重点：主题与顶栏共用 ThemeProvider；F1 仍不发起探活请求。

import { useThemeContext } from '../app/providers/themeContext'
import { ContentSection } from '../components/ui/ContentSection'
import { KeyValueList } from '../components/ui/KeyValueList'
import { Notice } from '../components/ui/Notice'
import { PageHeader } from '../components/ui/PageHeader'
import { THEME_LABELS, type ThemeMode } from '../hooks/useTheme'
import { API_BASE_URL } from '../services/api/config'

const THEME_OPTIONS: ThemeMode[] = ['system', 'light', 'dark']

export function SettingsPage() {
  const { mode, setMode } = useThemeContext()

  return (
    <div className="page">
      <PageHeader
        title="设置"
        description="外观与运行环境；本轮只做界面 Demo，不实现配置中心。"
      />

      <div className="page-content">
        <ContentSection
          title="外观"
          description="主题保存在 localStorage；跟随系统时会响应操作系统的深浅色。"
        >
          <div className="segmented" role="group" aria-label="主题模式">
            {THEME_OPTIONS.map((option) => (
              <button
                key={option}
                type="button"
                className="segmented__item"
                aria-pressed={mode === option}
                onClick={() => setMode(option)}
              >
                {THEME_LABELS[option]}
              </button>
            ))}
          </div>
        </ContentSection>

        <ContentSection title="后端连接">
          <KeyValueList
            items={[
              { label: 'API 基址', value: <code>{API_BASE_URL}</code> },
              { label: '连接状态', value: <span className="tag">连接待检测（F2）</span> },
              { label: '健康检查', value: <code>GET /healthz</code> },
            ]}
          />
          <Notice tone="info" title="F2 接入">
            真实探活、超时与错误提示将在 F2 实现。当前页面与顶栏都不会发起网络请求。
          </Notice>
        </ContentSection>

        <ContentSection title="关于">
          <KeyValueList
            items={[
              { label: '阶段', value: 'Codex 风格 UI Demo（基于 F1 骨架）' },
              { label: '前端版本', value: '0.0.0' },
              { label: '后端', value: 'FastAPI · 127.0.0.1:8001' },
              { label: '桌面壳', value: 'Tauri 2（未托管 Python）' },
            ]}
          />
        </ContentSection>

        <p className="demo-note">
          Demo 数据：本页除主题切换外不改变任何真实配置。
        </p>
      </div>
    </div>
  )
}

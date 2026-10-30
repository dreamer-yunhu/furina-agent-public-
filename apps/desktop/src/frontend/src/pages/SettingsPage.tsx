// ── AI-ASSISTED ── 本文件由 AI 生成/改写，待人工复核 ──
// 复核重点：
//   1. 密钥输入框是 type=password，**保存后立刻清空**，界面任何地方都不回显完整密钥。
//   2. 保存会重启后端（约 5–10 秒），期间顶栏会短暂变「未连接」，这是正常的。
//   3. 浏览器环境（vitest / 纯前端调试）没有 Tauri IPC，要显示"仅桌面端可用"，
//      而不是抛一个看不懂的错。

import { useEffect, useState } from 'react'

import { useBackend } from '../app/providers/backendContext'
import { useThemeContext } from '../app/providers/themeContext'
import { ContentSection } from '../components/ui/ContentSection'
import { KeyValueList } from '../components/ui/KeyValueList'
import { Notice } from '../components/ui/Notice'
import { PageHeader } from '../components/ui/PageHeader'
import { THEME_LABELS, type ThemeMode } from '../hooks/useTheme'
import { API_BASE_URL } from '../services/api/config'
import {
  clearKey,
  getKeyStatus,
  isDesktopShell,
  saveKey,
  type KeyStatus,
} from '../services/desktop/credentials'

const THEME_OPTIONS: ThemeMode[] = ['system', 'light', 'dark']

const STATUS_LABEL = {
  checking: '连接待检测',
  online: '已连接',
  offline: '未连接',
} as const

export function SettingsPage() {
  const { mode, setMode } = useThemeContext()
  const backend = useBackend()

  const [keyStatus, setKeyStatus] = useState<KeyStatus | null>(null)
  const [draftKey, setDraftKey] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | undefined>(undefined)
  const [notice, setNotice] = useState<string | undefined>(undefined)

  useEffect(() => {
    if (!isDesktopShell()) return
    let cancelled = false
    getKeyStatus()
      .then((status) => {
        if (!cancelled) setKeyStatus(status)
      })
      .catch((e: unknown) => {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e))
      })
    return () => {
      cancelled = true
    }
  }, [])

  const applyStatus = (status: KeyStatus) => {
    setKeyStatus(status)
    setDraftKey('')
    if (status.warning) {
      setError(`密钥已保存，但后端未能重启：${status.warning}`)
    } else {
      setError(undefined)
      setNotice('已保存到系统凭据管理器，后端正在重启（约 5–10 秒）。')
    }
  }

  const handleSave = async () => {
    const key = draftKey.trim()
    if (!key) return
    setBusy(true)
    setError(undefined)
    setNotice(undefined)
    try {
      applyStatus(await saveKey(key))
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  const handleClear = async () => {
    if (!window.confirm('清除后应用将无法调用模型，确定继续？')) return
    setBusy(true)
    setError(undefined)
    setNotice(undefined)
    try {
      applyStatus(await clearKey())
      setNotice('已从系统凭据管理器删除。')
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="page">
      <PageHeader
        title="设置"
        description="外观、模型密钥与运行环境。"
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

        <ContentSection
          title="模型密钥"
          description="保存在 Windows 凭据管理器，后端启动时以环境变量注入。凭据库为空时，后端仍会回退读取 %APPDATA%\furina-agent\.env（明文，兼容旧方式）。"
        >
          <KeyValueList
            items={[
              {
                label: '当前状态',
                value: (
                  <span className={keyStatus?.configured ? 'tag green' : 'tag'}>
                    {keyStatus?.label ?? '读取中…'}
                  </span>
                ),
              },
              { label: '存储位置', value: 'Windows 凭据管理器 · furina-agent' },
            ]}
          />

          <div className="segmented" style={{ marginTop: 12 }}>
            <input
              type="password"
              value={draftKey}
              placeholder="粘贴 DEEPSEEK_API_KEY"
              aria-label="模型 API Key"
              autoComplete="off"
              spellCheck={false}
              onChange={(event) => setDraftKey(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter') void handleSave()
              }}
              style={{ flex: 1, minWidth: 220 }}
            />
            <button
              type="button"
              className="btn primary"
              disabled={busy || !draftKey.trim()}
              onClick={() => void handleSave()}
            >
              {busy ? '保存中…' : '保存'}
            </button>
            <button
              type="button"
              className="btn"
              disabled={busy || !keyStatus?.configured}
              onClick={() => void handleClear()}
            >
              清除
            </button>
          </div>

          {error ? (
            <Notice tone="warning" title="操作未完成">
              {error}
            </Notice>
          ) : null}
          {notice ? (
            <Notice tone="info" title="提示">
              {notice}
            </Notice>
          ) : null}
          {!isDesktopShell() ? (
            <Notice tone="info" title="浏览器环境">
              密钥管理只在桌面应用中可用。
            </Notice>
          ) : null}
        </ContentSection>

        <ContentSection title="后端连接">
          <KeyValueList
            items={[
              { label: 'API 基址', value: <code>{API_BASE_URL}</code> },
              {
                label: '连接状态',
                value: (
                  <span
                    className={
                      backend.status === 'online' ? 'tag green' : 'tag amber'
                    }
                  >
                    {STATUS_LABEL[backend.status]}
                  </span>
                ),
              },
              {
                label: '最近错误',
                value: backend.error ? (
                  <code>{backend.error}</code>
                ) : (
                  '—'
                ),
              },
            ]}
          />
          <Notice tone="info" title="后端生命周期">
            后端由桌面壳托管：启动应用时拉起，关闭时回收；崩溃会自动变「未连接」并每 5 秒重试。
          </Notice>
        </ContentSection>

        <ContentSection title="关于">
          <KeyValueList
            items={[
              { label: '前端版本', value: '0.0.0' },
              { label: '后端', value: 'FastAPI · 127.0.0.1:8001（内置 exe）' },
              { label: '桌面壳', value: 'Tauri 2' },
            ]}
          />
        </ContentSection>
      </div>
    </div>
  )
}

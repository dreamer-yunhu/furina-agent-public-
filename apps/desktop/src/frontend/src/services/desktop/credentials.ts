// ── AI-ASSISTED ── 本文件由 AI 生成，待人工复核 ──
//
// 密钥管理的**桌面壳**通道（Tauri IPC，不是 HTTP）。
//
// 复核重点：
//   1. 密钥存在 Windows 凭据管理器，**不经过 HTTP、不落明文文件**；
//      后端拿到它靠的是 Rust 拉起进程时注入的环境变量。
//   2. 返回值里永远没有完整密钥，只有尾号。
//   3. 浏览器/vitest 环境下没有 Tauri，调用会明确失败而不是静默;

import { invoke } from '@tauri-apps/api/core'

export interface KeyStatus {
  configured: boolean
  label: string
  /** 密钥保存成功但后端没能重启时的原因 */
  warning?: string | null
}

export function isDesktopShell(): boolean {
  return (
    typeof window !== 'undefined' &&
    typeof (window as { __TAURI_INTERNALS__?: unknown }).__TAURI_INTERNALS__ ===
      'object'
  )
}

function assertDesktop(): void {
  if (!isDesktopShell()) {
    throw new Error('密钥管理只在桌面端可用（当前是浏览器环境）')
  }
}

export async function getKeyStatus(): Promise<KeyStatus> {
  assertDesktop()
  return invoke<KeyStatus>('api_key_status')
}

export async function saveKey(key: string): Promise<KeyStatus> {
  assertDesktop()
  return invoke<KeyStatus>('save_api_key', { key })
}

export async function clearKey(): Promise<KeyStatus> {
  assertDesktop()
  return invoke<KeyStatus>('clear_api_key')
}

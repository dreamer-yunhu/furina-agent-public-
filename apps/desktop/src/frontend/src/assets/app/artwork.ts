// ── AI-ASSISTED ── 本文件由 AI 生成，待人工复核 ──
// 美术资源集中入口：替换这里即可，业务组件不需要改。
//
// 用法（图片放在 src/assets/app/ 下，由 Vite 处理路径）：
//   import background from './background.webp'
//   import character from './character.png'
//   import logo from './logo.svg'
//   import avatar from './avatar.png'
//   import emptyState from './empty-state.svg'
//   export const artwork: ArtworkRegistry = {
//     background, character, logo, avatar, emptyState,
//   }
//
// 字段与使用位置：
//   background  → 工作台背景层（BackgroundSlot）
//   character   → 右下角角色入口（CharacterSlot）
//   logo        → 侧栏品牌 Logo
//   avatar      → 侧栏用户头像 + 消息中的 Agent 头像
//   emptyState  → 空状态插图（任务/执行/404）
//
// 约束：不要在这里引入未授权的 Live2D 模型或商业美术资源。
// 当前刻意留空，所有位置都会回退到中性占位/文字。

export interface ArtworkRegistry {
  background?: string
  character?: string
  logo?: string
  avatar?: string
  emptyState?: string
}

export const artwork: ArtworkRegistry = {}

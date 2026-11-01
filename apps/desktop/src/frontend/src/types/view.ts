// ── AI-ASSISTED ── 本文件由 AI 生成，待人工复核 ──
// 复核重点：
//   1. 这是**视图层**类型，不是后端 DTO（DTO 在 services/api/types.ts）。
//      两者刻意分开：后端字段是 snake_case，界面用 camelCase，映射只在一处做。
//   2. 本文件取代了原先的 `demo/types.ts` —— 删掉 demo 后，聊天组件只需要
//      渲染"已经归一好的消息"，不应该再知道数据从哪来。

export type ViewRole = 'user' | 'assistant' | 'system'

/** 聊天流里的一行消息（历史与流式共用） */
export interface ViewMessage {
  id: string
  role: ViewRole
  content: string
  /** 展示用时间；历史消息为空串（后端没有单条消息时间） */
  at: string
}

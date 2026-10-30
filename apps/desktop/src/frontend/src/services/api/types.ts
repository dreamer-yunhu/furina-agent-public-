// ── AI-ASSISTED ── 本文件由 AI 生成，待人工复核 ──
// 复核重点：这里是**后端 DTO**，与 demo/types.ts 是两套东西，不要合并。
// 后端字段是 snake_case（FastAPI 直出），前端不要为了顺手改成 camelCase ——
// 那会在边界上多一层映射，且一旦漏字段是静默的。

/** GET /agent/threads 的单项 */
export interface ApiThreadSummary {
  id: string
  title: string
  /** ISO 字符串，后端是**无时区**本地时间 */
  updated_at: string
  user_id: string
  created_at: string
}

/** GET /agent/threads 的信封 */
export interface ApiThreadList {
  items: ApiThreadSummary[]
  total: number
  page: number
  size: number
}

/** GET /healthz */
export interface ApiHealth {
  status: string
  checkpoint_store: boolean
  graph: boolean
  timeout_scanner: string
  llm_key_configured: boolean
}

/** GET /agent/threads/{id}/messages 的单项 */
export interface ApiMessage {
  id: string
  role: 'user' | 'assistant' | 'tool' | 'system'
  content: string
  name: string | null
  execution_id: string
  /** 由 state.result 补出来的助手回复（不是 messages 里的原始消息） */
  from_result?: boolean
}

export interface ApiMessageList {
  items: ApiMessage[]
  total: number
}

/** 送审的单个写操作预览（后端 `agent/contracts.py::WritePreview`） */
export interface ApiWritePreview {
  tool_call_id: string
  /** 数据库审批行 id；旧 checkpoint 里可能没有 */
  approval_id?: string | null
  /** 沙箱相对路径，不含盘符 */
  path: string
  /** 会自动创建的父目录（由浅到深），已存在时为空 */
  creates_dirs?: string[]
  is_new_file: boolean
  /** 乐观锁：审批期间文件被改过会拒绝执行 */
  old_hash?: string | null
  added: number
  removed: number
  diff: string
}

/** interrupt() 抛出的载荷 */
export interface ApiReviewRequest {
  type: 'review_request'
  action: 'review_request'
  requests: ApiWritePreview[]
}

export type ApiReviewAction = 'approve' | 'reject'

/** 单条裁决（后端 `ItemDecision`） */
export interface ApiItemDecision {
  tool_call_id?: string
  approval_id?: string | null
  action: ApiReviewAction
  reason?: string | null
}

/** Command(resume=) 收回的载荷 */
export interface ApiReviewDecision {
  type: 'review_decision'
  decisions: ApiItemDecision[]
}

/**
 * SSE 事件。类型是**封闭集**（后端 `agent/stream.py` 的 EVENT_TYPES），
 * 新增类型必须两边同步改，否则前端会静默丢弃。
 */
export type AgentEvent =
  | { type: 'token'; agent: string; content: string }
  | { type: 'tool_start'; agent?: string; id?: string; name?: string }
  | { type: 'tool_end'; agent?: string; id?: string }
  | {
      type: 'approval_required'
      agent: string
      interrupt_id: string
      review: ApiReviewRequest
    }
  | { type: 'error'; code?: string; message?: string }
  | { type: 'done'; status: string }

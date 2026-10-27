// ── AI-ASSISTED ── 本文件由 AI 生成，待人工复核 ──
// 复核重点：
//   1. F1 不发送任何请求，也不生成模拟消息；发送按钮保持禁用。
//   2. 输入框内容只是本地 UI 状态，刷新后不保留（符合 F1 边界）。

import { useState } from 'react'

import { EmptyState } from '../components/ui/EmptyState'
import { Notice } from '../components/ui/Notice'
import { PageHeader } from '../components/ui/PageHeader'
import { Panel } from '../components/ui/Panel'

interface ChatPageProps {
  threadId?: string
}

export function ChatPage({ threadId }: ChatPageProps) {
  const [draft, setDraft] = useState('')

  return (
    <div className="page">
      <PageHeader
        title="对话"
        description="会话入口与流式响应区域；真实数据将在 F2/F3 接入。"
        meta={
          threadId ? (
            <span className="mono">thread: {threadId}</span>
          ) : (
            <span className="muted">尚未创建会话</span>
          )
        }
      />

      <div className="chat-layout">
        <Panel
          title="消息"
          description="F1 只建立骨架，不显示任何模拟对话。"
          className="chat-layout__messages"
        >
          <EmptyState
            title="还没有消息"
            description="会话历史查询尚未实现（后端缺口见 F0 审计 P0-2）。"
            hint="F2 接入 POST /agent 与 SSE 后，这里显示真实的 token、工具事件与审批通知。"
          />
        </Panel>

        <Panel
          title="输入"
          description="任务提交与 SSE 尚未接线。"
          className="chat-layout__composer"
        >
          <label className="field">
            <span className="field__label">消息</span>
            <textarea
              className="field__input"
              rows={4}
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              placeholder="F1 暂不发送；F2 接入真实任务提交。"
            />
          </label>

          <div className="form-actions">
            <button type="button" className="button button--primary" disabled>
              发送（F2 接入）
            </button>
            <span className="form-actions__hint">
              当前不发起请求，也不写入本地假数据。
            </span>
          </div>

          <Notice tone="info" title="契约缺口">
            提交入口是 <code>POST /agent</code>（SSE），当前 SSE 不回传
            <code>task_id</code> / <code>execution_id</code>。F2 先冻结标识回传方式，
            再实现真实发送。
          </Notice>
        </Panel>
      </div>
    </div>
  )
}

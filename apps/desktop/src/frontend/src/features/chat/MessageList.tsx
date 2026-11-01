// ── AI-ASSISTED ── 本文件由 AI 生成/改写，待人工复核 ──
// 复核重点：
//   1. ★ 删掉了「消息后面跟一张审批卡片」的分支，因为它依赖 demo 数据
//      （真实接口不返回 message.approvalId）。审批的实时交互走
//      `PendingApproval`（来自 SSE 的 approval_required 事件），那是另一条链路。
//   2. 现在只做一件事：把消息数组渲染成行。

import { Fragment } from 'react'

import type { ViewMessage } from '../../types/view'
import { MessageRow } from './MessageRow'

export function MessageList({ messages }: { messages: ViewMessage[] }) {
  return (
    <>
      {messages.map((message) => (
        <Fragment key={message.id}>
          <MessageRow message={message} />
        </Fragment>
      ))}
    </>
  )
}

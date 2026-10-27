// ── AI-ASSISTED ── 本文件由 AI 生成，待人工复核 ──
// 复核重点：审批卡片跟在触发它的消息之后，不另起一份重复列表。

import { Fragment } from 'react'

import { getDemoApproval } from '../../demo/data'
import type { DemoMessage } from '../../demo/types'
import { ApprovalCard } from './ApprovalCard'
import { MessageRow } from './MessageRow'

export function MessageList({ messages }: { messages: DemoMessage[] }) {
  return (
    <>
      {messages.map((message) => {
        const approval = message.approvalId
          ? getDemoApproval(message.approvalId)
          : undefined

        return (
          <Fragment key={message.id}>
            <MessageRow message={message} />
            {approval ? (
              <div className="approval-wrap">
                <ApprovalCard approval={approval} />
              </div>
            ) : null}
          </Fragment>
        )
      })}
    </>
  )
}

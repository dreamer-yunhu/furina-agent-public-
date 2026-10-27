// ── AI-ASSISTED ── 本文件由 AI 生成，待人工复核 ──
// 复核重点：
//   1. 布局对齐 Codex 原型：chat-head / chat-scroll / conversation / composer。
//   2. 本地发送只追加 Demo 消息，不调用后端。
//   3. 欢迎页、空会话、未知会话三种状态分清。

import { useEffect, useRef, useState } from 'react'

import { Link } from '../app/Link'
import { getDemoMessages, getDemoThread, demoThreads } from '../demo/data'
import type { DemoMessage } from '../demo/types'
import { Composer } from '../features/chat/Composer'
import { ConversationHeader } from '../features/chat/ConversationHeader'
import { MessageList } from '../features/chat/MessageList'

interface ChatPageProps {
  threadId?: string
}

export function ChatPage({ threadId }: ChatPageProps) {
  const thread = threadId ? getDemoThread(threadId) : undefined
  const demoMessages = threadId ? getDemoMessages(threadId) : []
  const [localMessages, setLocalMessages] = useState<DemoMessage[]>([])
  const localId = useRef(0)
  const scrollRef = useRef<HTMLDivElement>(null)

  const messages = [...demoMessages, ...localMessages]
  const hasConversation = Boolean(thread) || localMessages.length > 0

  useEffect(() => {
    const node = scrollRef.current
    if (node) {
      node.scrollTop = node.scrollHeight
    }
  }, [messages.length])

  if (threadId && !thread) {
    return (
      <div className="chat-page">
        <div className="chat-empty-state">
          <span className="tag">Demo 数据</span>
          <h1>会话不存在</h1>
          <p>
            当前 Demo 数据没有包含这个会话 ID：<code>{threadId}</code>
          </p>
          <Link className="pill-btn" to="/chat">
            返回新会话
          </Link>
        </div>
      </div>
    )
  }

  const handleSend = (text: string) => {
    const index = localId.current
    localId.current += 1
    setLocalMessages((current) => [
      ...current,
      {
        id: `local-user-${index}`,
        role: 'user',
        content: text,
        at: '刚刚',
      },
      {
        id: `local-system-${index}`,
        role: 'system',
        content:
          'Demo：这条输入没有发送到后端，也没有进入主管图。F2 接入真实提交后才会产生 token 与工具事件。',
        at: '刚刚',
      },
    ])
  }

  return (
    <div className="chat-page">
      <ConversationHeader thread={thread} threadId={threadId} />

      <div className="chat-scroll" ref={scrollRef}>
        <div className="conversation">
          {hasConversation ? (
            messages.length ? (
              <MessageList messages={messages} />
            ) : (
              <div className="chat-empty-state chat-empty-state--inline">
                <h2>这个会话还没有消息</h2>
                <p>在下方输入框发送第一条消息（Demo 模式，不会调用后端）。</p>
              </div>
            )
          ) : (
            <div className="chat-welcome">
              <div className="chat-welcome__mark" aria-hidden="true">
                芙
              </div>
              <h2>今天想做什么？</h2>
              <p>
                这是一个 Codex 风格的工作台 Demo。会话、工具调用与审批卡片均为本地演示数据，
                不会调用真实 Agent。
              </p>
              <div className="chat-welcome__suggestions">
                {demoThreads.slice(0, 3).map((item) => (
                  <Link
                    key={item.id}
                    className="suggestion-chip"
                    to={`/chat/${item.id}`}
                  >
                    <span>{item.title}</span>
                    <span className="suggestion-chip__meta">
                      {item.updatedAt}
                    </span>
                  </Link>
                ))}
              </div>
            </div>
          )}

          {hasConversation ? (
            <div className="demo-note">
              ⓘ Demo 模式：审批操作仅改变本地演示状态，不会调用后端，也不会真正执行工具。
            </div>
          ) : null}
        </div>
      </div>

      <div className="composer-wrap">
        <Composer onSend={handleSend} />
      </div>
    </div>
  )
}

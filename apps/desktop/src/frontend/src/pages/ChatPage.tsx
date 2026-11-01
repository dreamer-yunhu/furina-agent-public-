// ── AI-ASSISTED ── 本文件由 AI 生成/改写，待人工复核 ──
// 复核重点：
//   1. ★ 删掉 demo 会话的整条分支，只保留真实后端一条路径。
//      `/chat`（尚无 threadId）发送第一条消息时**自动建线程再发送**：
//      先 POST /agent/threads，把待发文本存到模块级变量，navigate 到新线程，
//      由新挂载的页面接管发送（App 用 threadId 当 key，必然重挂载）。
//      为什么不在旧实例里直接发：旧实例会被卸载，流式内容会丢。
//   2. 审批仍是两步：先 /agent/decisions 落库，再 /agent/resume 续跑。
//   3. 未连接时明确报错，不再落入"本地演示消息"。

import { useEffect, useRef, useState } from 'react'

import { Link } from '../app/Link'
import { navigate } from '../app/router'
import { useBackend } from '../app/providers/backendContext'
import { Composer } from '../features/chat/Composer'
import { ConversationHeader } from '../features/chat/ConversationHeader'
import { MessageList } from '../features/chat/MessageList'
import { PendingApproval } from '../features/chat/PendingApproval'
import { getPending } from '../services/api/activity'
import { resumeChat, submitDecisions } from '../services/api/approvals'
import { streamChat } from '../services/api/chat'
import { listMessages } from '../services/api/messages'
import { createThread } from '../services/api/threads'
import type {
  AgentEvent,
  ApiItemDecision,
  ApiMessage,
  ApiReviewRequest,
} from '../services/api/types'
import type { ViewMessage } from '../types/view'

/**
 * 跨"建线程 → 重挂载"的一次性待发文本。
 * 只在自动建线程时使用；消费后立刻清空，避免刷新页面重复发送。
 */
let pendingFirstMessage: string | null = null

interface ChatPageProps {
  threadId?: string
}

type HistoryState = 'loading' | 'ready' | 'error'

interface HistorySnapshot {
  state: HistoryState
  items: ViewMessage[]
  error?: string
}

function toViewMessage(message: ApiMessage, index: number): ViewMessage {
  return {
    id: message.id || `hist-${index}`,
    role: message.role === 'assistant' ? 'assistant' : 'user',
    content: message.content,
    at: '',
  }
}

function titleFrom(text: string): string {
  const trimmed = text.trim().replace(/\s+/g, ' ')
  return (trimmed.slice(0, 40) || '新会话').slice(0, 255)
}

export function ChatPage({ threadId }: ChatPageProps) {
  const backend = useBackend()
  const online = backend.status === 'online'

  const [localMessages] = useState<ViewMessage[]>([])
  const scrollRef = useRef<HTMLDivElement>(null)

  const [history, setHistory] = useState<HistorySnapshot>({
    state: 'loading',
    items: [],
  })

  const [streamMessages, setStreamMessages] = useState<ViewMessage[]>([])
  const [streaming, setStreaming] = useState(false)
  const [streamError, setStreamError] = useState<string | undefined>(undefined)

  const [pendingReview, setPendingReview] = useState<ApiReviewRequest | null>(null)
  const [approvalBusy, setApprovalBusy] = useState(false)
  const [approvalError, setApprovalError] = useState<string | undefined>(undefined)

  // 读取历史（仅真实线程）
  useEffect(() => {
    if (!threadId || !online) return

    let cancelled = false
    listMessages(threadId)
      .then((list) => {
        if (cancelled) return
        const items = list.items
          .filter((item) => item.role === 'user' || item.role === 'assistant')
          .map(toViewMessage)
        setHistory({ state: 'ready', items })

        // 刷新页面后恢复"卡在审批中断"的卡片；失败不影响历史显示
        getPending(threadId)
          .then((result) => {
            if (cancelled) return
            if (result.pending?.review?.type === 'review_request') {
              setPendingReview(result.pending.review)
            }
          })
          .catch(() => {
            /* 忽略：恢复审批是增强，不该让历史也变成错误 */
          })
      })
      .catch((error: unknown) => {
        if (cancelled) return
        setHistory({
          state: 'error',
          items: [],
          error: error instanceof Error ? error.message : String(error),
        })
      })

    return () => {
      cancelled = true
    }
  }, [threadId, online])

  const messages = [...history.items, ...localMessages, ...streamMessages]

  useEffect(() => {
    const node = scrollRef.current
    if (node) node.scrollTop = node.scrollHeight
  }, [messages.length, streaming, pendingReview])

  /** 消费一次事件流（新消息或审批续跑都走这里） */
  const runTurn = async (
    events: AsyncGenerator<AgentEvent>,
    userText?: string,
  ) => {
    const stamp = Date.now()
    const userId = `local-user-${stamp}`
    const assistantId = `local-assistant-${stamp}`
    let acc = ''

    setStreamError(undefined)
    setApprovalError(undefined)
    setStreaming(true)
    setStreamMessages([
      ...(userText
        ? [{ id: userId, role: 'user' as const, content: userText, at: '刚刚' }]
        : []),
      { id: assistantId, role: 'assistant' as const, content: '', at: '刚刚' },
    ])

    try {
      for await (const event of events) {
        if (event.type === 'token') {
          acc += event.content
          setStreamMessages((current) =>
            current.map((message) =>
              message.id === assistantId ? { ...message, content: acc } : message,
            ),
          )
        } else if (event.type === 'approval_required') {
          setPendingReview(event.review)
        } else if (event.type === 'error') {
          setStreamError(event.message ?? event.code ?? '后端返回错误')
        }
      }
    } catch (error) {
      setStreamError(error instanceof Error ? error.message : String(error))
    } finally {
      // 把这一轮落进历史，避免刷新前内容只在 stream 状态里
      setHistory((current) => ({
        ...current,
        items: [
          ...current.items,
          ...(userText
            ? [{ id: userId, role: 'user' as const, content: userText, at: '刚刚' }]
            : []),
          ...(acc
            ? [
                {
                  id: assistantId,
                  role: 'assistant' as const,
                  content: acc,
                  at: '刚刚',
                },
              ]
            : []),
        ],
      }))
      setStreamMessages([])
      setStreaming(false)
    }
  }

  const sendReal = async (text: string, id: string) => {
    await runTurn(streamChat({ user_input: text, chat_thread_id: id }), text)
  }

  // 自动建线程后，由新挂载的页面接管首条消息
  useEffect(() => {
    if (!threadId || !online || !pendingFirstMessage) return
    const text = pendingFirstMessage
    pendingFirstMessage = null
    void sendReal(text, threadId)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [threadId, online])

  const handleApprovalSubmit = async (decisions: ApiItemDecision[]) => {
    if (!threadId) return
    setApprovalBusy(true)
    setApprovalError(undefined)
    try {
      // ① 先落库：即使后面续跑失败，决定仍然可查
      await submitDecisions(threadId, decisions)
      setPendingReview(null)
      // ② 再续跑
      await runTurn(resumeChat(threadId, decisions))
    } catch (error) {
      setApprovalError(error instanceof Error ? error.message : String(error))
    } finally {
      setApprovalBusy(false)
    }
  }

  const handleSend = (text: string) => {
    if (!online) {
      setStreamError('未连接本地服务：发送前请先确认后端已启动。')
      return
    }

    if (threadId) {
      void sendReal(text, threadId)
      return
    }

    // 尚无会话：先建线程，再把这条消息交给新页面
    pendingFirstMessage = text
    createThread(titleFrom(text))
      .then((created) => {
        backend.reload()
        navigate(`/chat/${created.id}`)
      })
      .catch((error: unknown) => {
        pendingFirstMessage = null
        setStreamError(
          `创建会话失败：${error instanceof Error ? error.message : String(error)}`,
        )
      })
  }

  if (threadId && !online) {
    return (
      <div className="chat-page">
        <div className="chat-empty-state">
          <span className="tag">未连接</span>
          <h1>无法加载会话</h1>
          <p>
            本地服务当前{backend.status === 'checking' ? '正在探测' : '未连接'}，读不到会话历史。
            {backend.error ? (
              <>
                <br />
                <code>{backend.error}</code>
              </>
            ) : null}
          </p>
          <Link className="pill-btn" to="/chat">
            返回新会话
          </Link>
        </div>
      </div>
    )
  }

  const threadTitle = threadId
    ? backend.threads.find((item) => item.id === threadId)?.title
    : undefined

  return (
    <div className="chat-page">
      <ConversationHeader title={threadTitle} threadId={threadId} />

      <div className="chat-scroll" ref={scrollRef}>
        <div className="conversation">
          {threadId ? (
            history.state === 'loading' ? (
              <div className="chat-empty-state chat-empty-state--inline">
                <h2>正在加载会话历史…</h2>
                <p>从本地服务的 checkpoint 读取。</p>
              </div>
            ) : history.state === 'error' ? (
              <div className="chat-empty-state chat-empty-state--inline">
                <h2>读取历史失败</h2>
                <p>
                  <code>{history.error}</code>
                </p>
              </div>
            ) : messages.length || pendingReview ? (
              <MessageList messages={messages} />
            ) : (
              <div className="chat-empty-state chat-empty-state--inline">
                <h2>这个会话还没有消息</h2>
                <p>在下方输入框发送第一条消息，它会真实进入主管图。</p>
              </div>
            )
          ) : (
            <div className="chat-welcome">
              <div className="chat-welcome__mark" aria-hidden="true">
                芙
              </div>
              <h2>今天想做什么？</h2>
              <p>
                {online
                  ? '直接输入即可：发送时会自动创建会话并写入后端。'
                  : '未连接本地服务，暂时无法创建会话。'}
              </p>
            </div>
          )}

          {pendingReview ? (
            <div className="approval-wrap">
              <PendingApproval
                review={pendingReview}
                busy={approvalBusy}
                error={approvalError}
                onSubmit={handleApprovalSubmit}
              />
            </div>
          ) : null}

          {streamError ? (
            <div className="demo-note" role="alert">
              ⚠ {streamError}
            </div>
          ) : null}
        </div>
      </div>

      <div className="composer-wrap">
        <Composer onSend={handleSend} disabled={streaming || Boolean(pendingReview)} />
      </div>
    </div>
  )
}

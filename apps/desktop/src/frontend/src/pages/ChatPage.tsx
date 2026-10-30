// ── AI-ASSISTED ── 本文件由 AI 生成，待人工复核 ──
// 复核重点：
//   1. 两条数据路径必须分清：Demo 会话（id 在 demo/data.ts 里）与真实会话
//      （后端 agent_thread 表）。**不能靠"该 id 有没有 demo 数据"来猜在线与否**，
//      必须同时看 backend.status。
//   2. 真实会话的历史由后端按每次执行拼出来，前端只做映射；不要在前端再拼一次。
//   3. 流式期间 token 是增量到达的，用累加变量 `acc` 收尾，避免多处读 state 造成丢字。
//   4. 审批是**两步**：先 /agent/decisions 落库，再 /agent/resume 续跑。
//      顺序反了会丢审计（决定没落库但图已经跑完）。
//   5. 页面重新挂载会丢掉"待审批"状态（后端没有"查询挂起项"的接口）。
//      这是已知缺口：审批做到一半刷新页面，卡片不会再出现。

import { useEffect, useRef, useState } from 'react'

import { Link } from '../app/Link'
import { useBackend } from '../app/providers/backendContext'
import { getDemoMessages, getDemoThread, demoThreads } from '../demo/data'
import type { DemoMessage, DemoThread } from '../demo/types'
import { Composer } from '../features/chat/Composer'
import { ConversationHeader } from '../features/chat/ConversationHeader'
import { MessageList } from '../features/chat/MessageList'
import { PendingApproval } from '../features/chat/PendingApproval'
import { getPending } from '../services/api/activity'
import { resumeChat, submitDecisions } from '../services/api/approvals'
import { streamChat } from '../services/api/chat'
import { listMessages } from '../services/api/messages'
import type {
  AgentEvent,
  ApiItemDecision,
  ApiMessage,
  ApiReviewRequest,
} from '../services/api/types'

interface ChatPageProps {
  threadId?: string
}

type HistoryState = 'loading' | 'ready' | 'error'

interface HistorySnapshot {
  state: HistoryState
  items: DemoMessage[]
  error?: string
}

function toViewMessage(message: ApiMessage, index: number): DemoMessage {
  return {
    // 由 state.result 补出来的那条没有 id，用下标兜底，避免 key 重复
    id: message.id || `hist-${index}`,
    role: message.role === 'assistant' ? 'assistant' : 'user',
    content: message.content,
    at: '',
  }
}

export function ChatPage({ threadId }: ChatPageProps) {
  const backend = useBackend()

  const demoThread = threadId ? getDemoThread(threadId) : undefined
  const isDemoThread = Boolean(demoThread)
  // 只有"不是 Demo 会话 + 后端在线"才走真实路径
  const isRealThread = Boolean(threadId) && !isDemoThread && backend.status === 'online'

  const demoMessages = threadId && isDemoThread ? getDemoMessages(threadId) : []
  const [localMessages, setLocalMessages] = useState<DemoMessage[]>([])
  const localId = useRef(0)
  const scrollRef = useRef<HTMLDivElement>(null)

  const [history, setHistory] = useState<HistorySnapshot>({
    state: 'loading',
    items: [],
  })

  const [streamMessages, setStreamMessages] = useState<DemoMessage[]>([])
  const [streaming, setStreaming] = useState(false)
  const [streamError, setStreamError] = useState<string | undefined>(undefined)

  // 真实挂起中的审批批次
  const [pendingReview, setPendingReview] = useState<ApiReviewRequest | null>(null)
  const [approvalBusy, setApprovalBusy] = useState(false)
  const [approvalError, setApprovalError] = useState<string | undefined>(undefined)

  useEffect(() => {
    if (!isRealThread || !threadId) return

    let cancelled = false
    listMessages(threadId)
      .then((list) => {
        if (cancelled) return
        const items = list.items
          .filter((item) => item.role === 'user' || item.role === 'assistant')
          .map(toViewMessage)
        setHistory({ state: 'ready', items })

        // 历史读完之后再查一次"是否停在审批中断上"：
        // 没有这一步，刷新页面就再也看不到那个待审批卡片，只能重新发起。
        // 失败不改变页面状态 —— 恢复审批是增强，不该让历史也显示成错误。
        getPending(threadId)
          .then((result) => {
            if (cancelled) return
            if (result.pending?.review?.type === 'review_request') {
              setPendingReview(result.pending.review)
            }
          })
          .catch(() => {
            /* 忽略：见上 */
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
  }, [isRealThread, threadId])

  const messages = isDemoThread
    ? [...demoMessages, ...localMessages]
    : [...history.items, ...streamMessages]

  const hasConversation = Boolean(threadId)

  useEffect(() => {
    const node = scrollRef.current
    if (node) {
      node.scrollTop = node.scrollHeight
    }
  }, [messages.length, streaming, pendingReview])

  /**
   * 消费一次事件流（新消息或审批续跑都走这里）。
   * `userText` 只有首次发送时给；续跑时不该再插一条用户消息。
   */
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
          // 中断：本轮到此为止，等待用户裁决
          setPendingReview(event.review)
        } else if (event.type === 'error') {
          setStreamError(event.message ?? event.code ?? '后端返回错误')
        }
      }
    } catch (error) {
      setStreamError(error instanceof Error ? error.message : String(error))
    } finally {
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
    if (isRealThread && threadId) {
      void sendReal(text, threadId)
      return
    }

    const index = localId.current
    localId.current += 1
    setLocalMessages((current) => [
      ...current,
      { id: `local-user-${index}`, role: 'user', content: text, at: '刚刚' },
      {
        id: `local-system-${index}`,
        role: 'system',
        content:
          backend.status === 'online'
            ? '这是 Demo 会话：它的消息不会进入后端。请在左侧选择真实会话，或新建后由后端创建。'
            : '未连接本地服务：这条输入没有发送到任何后端。启动服务后重试。',
        at: '刚刚',
      },
    ])
  }

  // 真实会话在离线时不能假装它不存在 —— 要明确说是"连不上"，而不是"没有"
  if (threadId && !isDemoThread && backend.status !== 'online') {
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

  const headerThread: DemoThread | undefined =
    demoThread ??
    (threadId
      ? {
          id: threadId,
          title: '已连接会话',
          preview: '',
          updatedAt: '',
          status: 'idle',
          pendingApprovals: 0,
        }
      : undefined)

  return (
    <div className="chat-page">
      <ConversationHeader
        thread={headerThread}
        threadId={threadId}
        backendMode={isRealThread}
      />

      <div className="chat-scroll" ref={scrollRef}>
        <div className="conversation">
          {hasConversation ? (
            isRealThread && history.state === 'loading' ? (
              <div className="chat-empty-state chat-empty-state--inline">
                <h2>正在加载会话历史…</h2>
                <p>从本地服务的 checkpoint 读取。</p>
              </div>
            ) : isRealThread && history.state === 'error' ? (
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
                <p>
                  {isRealThread
                    ? '在下方输入框发送第一条消息，它会真实进入主管图。'
                    : '在下方输入框发送第一条消息（Demo 模式，不会调用后端）。'}
                </p>
              </div>
            )
          ) : (
            <div className="chat-welcome">
              <div className="chat-welcome__mark" aria-hidden="true">
                芙
              </div>
              <h2>今天想做什么？</h2>
              <p>
                从左侧选择一个会话继续，或点「新建会话」开始一段真实对话。
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
              ⚠ 发送失败：{streamError}
            </div>
          ) : null}

          {hasConversation && !isRealThread ? (
            <div className="demo-note">
              ⓘ Demo 模式：审批操作仅改变本地演示状态，不会调用后端，也不会真正执行工具。
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

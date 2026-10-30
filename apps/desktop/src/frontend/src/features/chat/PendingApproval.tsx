// ── AI-ASSISTED ── 本文件由 AI 生成，待人工复核 ──
//
// 真实审批卡片（对应后端 `approval_required` 事件里的 review 载荷）。
//
// 复核重点：
//   1. **必须收齐所有裁决再提交**。后端 resume 会逐条比对挂起项，
//      少一条就是 409 —— 所以这里没有"单条立即提交"的交互。
//   2. `approval_id` 优先、`tool_call_id` 兜底：两者都回传，后端按 approval_id
//      精确落库；旧 checkpoint 没有 approval_id 时才靠 tool_call_id。
//   3. 批准 ≠ 执行成功：按钮文案和提示都必须保持这个区分。

import { useState } from 'react'

import type {
  ApiItemDecision,
  ApiReviewAction,
  ApiReviewRequest,
} from '../../services/api/types'

interface PendingApprovalProps {
  review: ApiReviewRequest
  busy: boolean
  error?: string
  onSubmit: (decisions: ApiItemDecision[]) => void
}

function keyOf(request: { approval_id?: string | null; tool_call_id: string }) {
  return request.approval_id || request.tool_call_id
}

export function PendingApproval({
  review,
  busy,
  error,
  onSubmit,
}: PendingApprovalProps) {
  const [choices, setChoices] = useState<Record<string, ApiReviewAction>>({})

  const requests = review.requests ?? []
  const allDecided = requests.every((item) => choices[keyOf(item)])

  const choose = (id: string, action: ApiReviewAction) => {
    setChoices((current) => ({ ...current, [id]: action }))
  }

  const submit = () => {
    if (!allDecided || busy) return
    const decisions: ApiItemDecision[] = requests.map((item) => ({
      tool_call_id: item.tool_call_id,
      approval_id: item.approval_id ?? null,
      action: choices[keyOf(item)],
    }))
    onSubmit(decisions)
  }

  return (
    <div className="approval">
      <div className="approval-top">
        <span className="tag amber">● 待审批 {requests.length} 项</span>
        <span className="tag">真实审批</span>
        <span className="right">
          批准只授权本次调用，不代表执行成功
        </span>
      </div>

      <div className="approval-body">
        {requests.map((item) => {
          const id = keyOf(item)
          const choice = choices[id]
          return (
            <div className="field" key={id}>
              <div className="target-line">
                <span className="label">
                  {item.is_new_file ? '新建文件' : '修改文件'}
                </span>
                <span className="target mono">{item.path}</span>
                <span className="right">
                  +{item.added} / -{item.removed}
                </span>
              </div>

              {item.creates_dirs?.length ? (
                <div className="summary">
                  将自动创建目录：{item.creates_dirs.join(' / ')}
                </div>
              ) : null}

              {item.old_hash ? (
                <div className="summary">
                  乐观锁：若该文件在审批期间被改动，本次批准会被拒绝执行。
                </div>
              ) : null}

              <details>
                <summary className="summary">查看 diff</summary>
                <pre className="approval-diff mono">{item.diff}</pre>
              </details>

              <div className="approval-actions">
                <button
                  type="button"
                  className="btn"
                  aria-pressed={choice === 'reject'}
                  onClick={() => choose(id, 'reject')}
                >
                  {choice === 'reject' ? '● 拒绝' : '拒绝'}
                </button>
                <button
                  type="button"
                  className="btn primary"
                  aria-pressed={choice === 'approve'}
                  onClick={() => choose(id, 'approve')}
                >
                  {choice === 'approve' ? '● 批准' : '批准'}
                </button>
              </div>
            </div>
          )
        })}

        {error ? (
          <div className="warning" role="alert">
            ⚠ 提交失败：{error}
          </div>
        ) : null}

        <div className="approval-actions">
          <button
            type="button"
            className="btn primary"
            onClick={submit}
            disabled={!allDecided || busy}
          >
            {busy
              ? '正在提交…'
              : allDecided
                ? '提交决定并继续'
                : '请为每一项做出选择'}
          </button>
        </div>
      </div>
    </div>
  )
}

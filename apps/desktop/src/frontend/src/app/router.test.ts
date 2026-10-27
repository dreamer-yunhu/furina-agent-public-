// ── AI-ASSISTED ── 本文件由 AI 生成，待人工复核 ──

import { describe, expect, it } from 'vitest'

import { matchPath } from './router'

describe('matchPath', () => {
  it('maps the root path to chat', () => {
    expect(matchPath('/')).toEqual({ name: 'chat', params: {}, path: '/chat' })
  })

  it('matches chat without a thread id', () => {
    expect(matchPath('/chat')).toEqual({ name: 'chat', params: {}, path: '/chat' })
  })

  it('extracts optional route params', () => {
    const match = matchPath('/chat/thread-1')
    expect(match.name).toBe('chat')
    expect(match.params.threadId).toBe('thread-1')
  })

  it('matches task detail', () => {
    const match = matchPath('/tasks/task-1')
    expect(match.name).toBe('task-detail')
    expect(match.params.taskId).toBe('task-1')
  })

  it('matches execution detail with two params', () => {
    const match = matchPath('/tasks/task-1/executions/execution-1')
    expect(match.name).toBe('execution-detail')
    expect(match.params).toEqual({
      taskId: 'task-1',
      executionId: 'execution-1',
    })
  })

  it('matches approval detail', () => {
    const match = matchPath('/approvals/approval-1')
    expect(match.name).toBe('approval-detail')
    expect(match.params.approvalRequestId).toBe('approval-1')
  })

  it('ignores query strings and trailing slashes', () => {
    expect(matchPath('/tasks?status=PENDING').name).toBe('tasks')
    expect(matchPath('/tasks/').name).toBe('tasks')
  })

  it('decodes params safely', () => {
    expect(matchPath('/chat/hello%20world').params.threadId).toBe('hello world')
  })

  it('falls back to not-found', () => {
    expect(matchPath('/unknown/page').name).toBe('not-found')
  })
})

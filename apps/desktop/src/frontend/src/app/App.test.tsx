// ── AI-ASSISTED ── 本文件由 AI 生成，待人工复核 ──
// 复核重点：
//   1. ★ 删掉 demo 后，详情页会真的发请求。测试里**必须 mock 接口层**，
//      否则用例结果取决于本机有没有起后端（上一版靠"jsdom 无 fetch"侥幸通过）。
//   2. 只测路由与布局；不测后端行为（那是 pytest 的事）。

import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { App } from './App'

// ── 接口层替身 ───────────────────────────────────────────────────────────
// 返回固定数据，让页面能进入 ready 态；断言只针对渲染结果。
vi.mock('../services/api/activity', () => ({
  listTasks: vi.fn(async () => ({ items: [], total: 0, page: 1, size: 20 })),
  listApprovals: vi.fn(async () => ({ items: [], total: 0, page: 1, size: 50 })),
  getPending: vi.fn(async () => ({ pending: null })),
  getTask: vi.fn(async (taskId: string) => ({
    id: taskId,
    thread_id: 'thread-lab-summary',
    thread_title: '测试会话',
    instruction: '整理实验结果并生成摘要',
    status: 'COMPLETED',
    failure_reason: null,
    created_at: '2026-10-30T10:00:00',
    updated_at: '2026-10-30T10:05:00',
    executions: [],
    approvals: [],
  })),
  getExecution: vi.fn(),
  getApproval: vi.fn(),
}))

vi.mock('../services/api/threads', () => ({
  listThreads: vi.fn(async () => ({ items: [], total: 0, page: 1, size: 100 })),
  createThread: vi.fn(),
  renameThread: vi.fn(),
  deleteThread: vi.fn(),
}))

function setHash(hash: string) {
  window.history.replaceState(null, '', hash)
  window.dispatchEvent(new Event('hashchange'))
}

describe('App navigation', () => {
  beforeEach(() => {
    setHash('#/chat')
  })

  it('renders the new-chat welcome page by default', () => {
    render(<App />)

    expect(
      screen.getByRole('heading', { level: 1, name: '新建会话' }),
    ).toBeInTheDocument()
    expect(
      screen.getByRole('heading', { level: 2, name: '今天想做什么？' }),
    ).toBeInTheDocument()
  })

  it('navigates to the tasks page from the sidebar', async () => {
    render(<App />)

    fireEvent.click(screen.getByTitle('任务'))

    expect(
      await screen.findByRole('heading', { level: 1, name: '任务' }),
    ).toBeInTheDocument()
    expect(window.location.hash).toBe('#/tasks')
    expect(screen.getByTitle('任务')).toHaveAttribute(
      'aria-current',
      'page',
    )
  })

  it('navigates to the audit page from the sidebar', async () => {
    render(<App />)

    fireEvent.click(screen.getByTitle('审计'))

    expect(
      await screen.findByRole('heading', { level: 1, name: '审批审计' }),
    ).toBeInTheDocument()
    expect(window.location.hash).toBe('#/audit')
  })

  it('renders task detail from the route param (mocked API)', async () => {
    setHash('#/tasks/task-lab-summary')
    render(<App />)

    expect(
      await screen.findByRole('heading', {
        level: 1,
        name: '整理实验结果并生成摘要',
      }),
    ).toBeInTheDocument()
    expect(screen.getAllByText('task-lab-summary').length).toBeGreaterThan(0)
  })

  it('renders a not-found page for unknown routes', () => {
    setHash('#/unknown')
    render(<App />)

    expect(
      screen.getByRole('heading', { level: 1, name: '页面不存在' }),
    ).toBeInTheDocument()
  })

  it('redirects the root path to chat', async () => {
    setHash('#/')
    render(<App />)

    expect(
      await screen.findByRole('heading', { level: 1, name: '新建会话' }),
    ).toBeInTheDocument()
    await waitFor(() => expect(window.location.hash).toBe('#/chat'))
  })

  it('collapses the sidebar from the header', () => {
    const { container } = render(<App />)

    fireEvent.click(screen.getByRole('button', { name: '收起侧栏' }))

    expect(container.querySelector('.workbench')).toHaveAttribute(
      'data-sidebar',
      'collapsed',
    )
    expect(
      screen.getByRole('button', { name: '展开侧栏' }),
    ).toBeInTheDocument()
  })

  it('opens the inspector on a conversation', async () => {
    setHash('#/chat/thread-lab-summary')
    render(<App />)

    fireEvent.click(screen.getByRole('button', { name: '详情面板' }))

    // 详情面板现在读真实接口（已 mock），断言它渲染出统计字段
    expect(await screen.findByText('任务数')).toBeInTheDocument()
    expect(screen.getByText('审批数')).toBeInTheDocument()
  })

  it('switches theme from settings and updates the document root', () => {
    setHash('#/settings')
    render(<App />)

    fireEvent.click(screen.getByRole('button', { name: '深色' }))
    expect(document.documentElement.dataset.theme).toBe('dark')

    fireEvent.click(screen.getByRole('button', { name: '浅色' }))
    expect(document.documentElement.dataset.theme).toBe('light')

    fireEvent.click(screen.getByRole('button', { name: '跟随系统' }))
    expect(document.documentElement.dataset.theme).toBeUndefined()
  })
})

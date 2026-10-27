// ── AI-ASSISTED ── 本文件由 AI 生成，待人工复核 ──
// 复核重点：只测前端路由与布局，不启动后端、不 mock 业务数据。

import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it } from 'vitest'

import { App } from './App'

function setHash(hash: string) {
  window.history.replaceState(null, '', hash)
  window.dispatchEvent(new Event('hashchange'))
}

describe('App navigation', () => {
  beforeEach(() => {
    setHash('#/chat')
  })

  it('renders the chat page by default', () => {
    render(<App />)
    expect(
      screen.getByRole('heading', { level: 1, name: '对话' }),
    ).toBeInTheDocument()
  })

  it('navigates to the tasks page from the sidebar', async () => {
    render(<App />)

    fireEvent.click(screen.getByRole('link', { name: /任务/ }))

    expect(
      await screen.findByRole('heading', { level: 1, name: '任务' }),
    ).toBeInTheDocument()
    expect(window.location.hash).toBe('#/tasks')
    expect(screen.getByRole('link', { name: /任务/ })).toHaveAttribute(
      'aria-current',
      'page',
    )
  })

  it('renders task detail from a route param', () => {
    setHash('#/tasks/task-123')
    render(<App />)

    expect(
      screen.getByRole('heading', { level: 1, name: '任务详情' }),
    ).toBeInTheDocument()
    expect(screen.getAllByText('task-123').length).toBeGreaterThan(0)
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
      await screen.findByRole('heading', { level: 1, name: '对话' }),
    ).toBeInTheDocument()
    await waitFor(() => expect(window.location.hash).toBe('#/chat'))
  })
})

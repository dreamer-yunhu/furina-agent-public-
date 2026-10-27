// ── AI-ASSISTED ── 本文件由 AI 生成，待人工复核 ──
// 复核重点：只测前端路由、布局与 Demo 交互，不启动后端、不 mock 业务数据。

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

  it('renders task detail from a demo route param', () => {
    setHash('#/tasks/task-lab-summary')
    render(<App />)

    expect(
      screen.getByRole('heading', {
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

  it('opens the inspector on a conversation', () => {
    setHash('#/chat/thread-lab-summary')
    render(<App />)

    fireEvent.click(screen.getByRole('button', { name: '详情面板' }))

    expect(screen.getByText('当前任务详情')).toBeInTheDocument()
    expect(screen.getByText('最近工具调用')).toBeInTheDocument()
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

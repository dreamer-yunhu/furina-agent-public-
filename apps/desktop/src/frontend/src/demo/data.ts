// ── AI-ASSISTED ── 本文件由 AI 生成，待人工复核 ──
// 复核重点：
//   1. 所有内容都是**演示数据**，页面上必须显示 Demo 标识；不得据此推断后端真实状态。
//   2. 审批状态（pending/approved/rejected）与工具执行状态（pending/succeeded/failed）
//      是两套独立字段，演示数据刻意保留了「已批准但执行失败」的组合。
//   3. 时间使用固定展示字符串，不依赖 Date.now()，保证截图与测试稳定。

import type {
  DemoApproval,
  DemoExecution,
  DemoMessage,
  DemoTask,
  DemoThread,
} from './types'

export const demoThreads: DemoThread[] = [
  {
    id: 'thread-lab-summary',
    title: '整理实验结果并生成摘要',
    preview: '等待写入 reports/experiment-summary.md 的审批',
    updatedAt: '今天 10:42',
    status: 'waiting_approval',
    pendingApprovals: 1,
  },
  {
    id: 'thread-rag-recall',
    title: '排查 RAG 检索召回下降',
    preview: '已定位到 chunk 切分参数，排查笔记已写入',
    updatedAt: '今天 09:18',
    status: 'completed',
    pendingApprovals: 0,
  },
  {
    id: 'thread-preflight',
    title: '重构审批恢复的预检逻辑',
    preview: '执行失败：目标文件在审批期间被修改',
    updatedAt: '昨天 18:20',
    status: 'failed',
    pendingApprovals: 0,
  },
  {
    id: 'thread-weekly',
    title: '写一份本周进度周报',
    preview: '新建会话，尚未开始',
    updatedAt: '昨天 16:05',
    status: 'idle',
    pendingApprovals: 0,
  },
]

const executions: DemoExecution[] = [
  {
    id: 'exec-lab-1',
    taskId: 'task-lab-summary',
    status: 'running',
    startedAt: '今天 10:39',
    summary: '读取实验记录，等待摘要文件写入审批',
    toolCalls: [
      {
        id: 'tool-lab-read',
        name: 'read_file',
        target: 'experiments/2026-10-27-baseline.md',
        status: 'succeeded',
        summary: '读取 128 行',
        at: '10:39',
      },
      {
        id: 'tool-lab-write',
        name: 'write_file',
        target: 'reports/experiment-summary.md',
        status: 'pending',
        summary: '等待用户决定',
        at: '10:41',
      },
    ],
  },
  {
    id: 'exec-rag-1',
    taskId: 'task-rag-recall',
    status: 'completed',
    startedAt: '今天 09:08',
    finishedAt: '今天 09:14',
    summary: '检索调试记录并写入排查笔记',
    toolCalls: [
      {
        id: 'tool-rag-search',
        name: 'search_docs',
        target: 'knowledge/rag/**',
        status: 'succeeded',
        summary: '命中 12 条调试记录',
        at: '09:08',
      },
      {
        id: 'tool-rag-write',
        name: 'write_file',
        target: 'notes/rag-debug.md',
        status: 'succeeded',
        summary: '写入 18 行',
        at: '09:13',
      },
    ],
  },
  {
    id: 'exec-rag-2',
    taskId: 'task-rag-recall',
    status: 'completed',
    startedAt: '今天 09:15',
    finishedAt: '今天 09:18',
    summary: '第二次执行：复核并补充结论',
    toolCalls: [
      {
        id: 'tool-rag-read',
        name: 'read_file',
        target: 'notes/rag-debug.md',
        status: 'succeeded',
        summary: '读取 18 行',
        at: '09:15',
      },
      {
        id: 'tool-rag-write-2',
        name: 'write_file',
        target: 'notes/rag-debug.md',
        status: 'succeeded',
        summary: '追加 6 行结论',
        at: '09:17',
      },
    ],
  },
  {
    id: 'exec-preflight-1',
    taskId: 'task-preflight',
    status: 'failed',
    startedAt: '昨天 18:12',
    finishedAt: '昨天 18:15',
    summary: '审批通过后目标文件被修改，执行失败',
    toolCalls: [
      {
        id: 'tool-preflight-write',
        name: 'write_file',
        target: 'scripts/cleanup.sh',
        status: 'failed',
        summary: 'old_hash 不匹配，拒绝覆盖',
        at: '18:15',
      },
    ],
  },
]

export const demoApprovals: DemoApproval[] = [
  {
    id: 'approval-write-summary',
    threadId: 'thread-lab-summary',
    taskId: 'task-lab-summary',
    executionId: 'exec-lab-1',
    toolName: 'write_file',
    target: 'reports/experiment-summary.md',
    summary: '创建新文件并写入 42 行实验摘要',
    risk: 'high',
    status: 'pending',
    requestedAt: '今天 10:41',
    toolExecutionStatus: 'pending',
  },
  {
    id: 'approval-write-rag-note',
    threadId: 'thread-rag-recall',
    taskId: 'task-rag-recall',
    executionId: 'exec-rag-1',
    toolName: 'write_file',
    target: 'notes/rag-debug.md',
    summary: '新建 18 行排查笔记',
    risk: 'low',
    status: 'approved',
    requestedAt: '今天 09:12',
    decidedAt: '今天 09:14',
    decidedBy: '本地用户（Demo）',
    toolExecutionStatus: 'succeeded',
    toolResult: '写入成功，18 行。',
  },
  {
    id: 'approval-edit-limits',
    threadId: 'thread-rag-recall',
    taskId: 'task-rag-recall',
    executionId: 'exec-rag-1',
    toolName: 'write_file',
    target: 'config/limits.toml',
    summary: '把 batch 上限从 20 改为 50',
    risk: 'medium',
    status: 'rejected',
    requestedAt: '今天 09:05',
    decidedAt: '今天 09:07',
    decidedBy: '本地用户（Demo）',
    decisionReason: '不要直接改默认限流参数，先加环境变量开关。',
    toolExecutionStatus: 'skipped',
  },
  {
    id: 'approval-cleanup-script',
    threadId: 'thread-preflight',
    taskId: 'task-preflight',
    executionId: 'exec-preflight-1',
    toolName: 'write_file',
    target: 'scripts/cleanup.sh',
    summary: '覆盖清理脚本（-12 / +18 行）',
    risk: 'high',
    status: 'approved',
    requestedAt: '昨天 18:12',
    decidedAt: '昨天 18:14',
    decidedBy: '本地用户（Demo）',
    toolExecutionStatus: 'failed',
    toolResult: '审批通过，但目标文件在审批期间被修改，未写入。',
  },
]

export const demoTasks: DemoTask[] = [
  {
    id: 'task-lab-summary',
    threadId: 'thread-lab-summary',
    title: '整理实验结果并生成摘要',
    status: 'waiting_approval',
    updatedAt: '今天 10:42',
    executions: executions.filter((item) => item.taskId === 'task-lab-summary'),
    approvalIds: ['approval-write-summary'],
  },
  {
    id: 'task-rag-recall',
    threadId: 'thread-rag-recall',
    title: '排查 RAG 检索召回下降',
    status: 'completed',
    updatedAt: '今天 09:18',
    executions: executions.filter((item) => item.taskId === 'task-rag-recall'),
    approvalIds: ['approval-write-rag-note', 'approval-edit-limits'],
  },
  {
    id: 'task-preflight',
    threadId: 'thread-preflight',
    title: '重构审批恢复的预检逻辑',
    status: 'failed',
    updatedAt: '昨天 18:20',
    executions: executions.filter((item) => item.taskId === 'task-preflight'),
    approvalIds: ['approval-cleanup-script'],
  },
  {
    id: 'task-weekly',
    threadId: 'thread-weekly',
    title: '写一份本周进度周报',
    status: 'idle',
    updatedAt: '昨天 16:05',
    executions: [],
    approvalIds: [],
  },
]

const messagesByThread: Record<string, DemoMessage[]> = {
  'thread-lab-summary': [
    {
      id: 'msg-lab-1',
      role: 'user',
      content:
        '把今天的 baseline 实验结果整理成一份摘要，写到 reports/experiment-summary.md。',
      at: '10:39',
    },
    {
      id: 'msg-lab-2',
      role: 'assistant',
      content: '我先读取实验记录，确认指标和结论。',
      at: '10:39',
      toolCalls: [executions[0].toolCalls[0]],
    },
    {
      id: 'msg-lab-3',
      role: 'assistant',
      content:
        '记录已读取：recall@10 比上周高 3.2 个百分点。接下来要创建摘要文件——这是写操作，先送审批。',
      at: '10:41',
      toolCalls: [executions[0].toolCalls[1]],
      approvalId: 'approval-write-summary',
    },
  ],
  'thread-rag-recall': [
    {
      id: 'msg-rag-1',
      role: 'user',
      content: 'RAG 召回最近掉了，帮我查一下原因。',
      at: '09:04',
    },
    {
      id: 'msg-rag-2',
      role: 'assistant',
      content: '我先看一下最近的限流配置，同时会检索调试记录。',
      at: '09:05',
      approvalId: 'approval-edit-limits',
    },
    {
      id: 'msg-rag-3',
      role: 'assistant',
      content: '限流配置的修改被拒绝，我不会改动 limits.toml。继续检索调试记录。',
      at: '09:08',
      toolCalls: [executions[1].toolCalls[0]],
    },
    {
      id: 'msg-rag-4',
      role: 'assistant',
      content:
        '定位到 chunk 切分从 800 改到 1200 后，长文档召回下降。把排查结论写到 notes/rag-debug.md。',
      at: '09:13',
      toolCalls: [executions[1].toolCalls[1]],
      approvalId: 'approval-write-rag-note',
    },
    {
      id: 'msg-rag-5',
      role: 'assistant',
      content: '排查完成。要不要我继续做一个最小复现脚本？',
      at: '09:18',
    },
    {
      id: 'msg-rag-6',
      role: 'system',
      content: 'Demo 数据：审批与执行结果均为本地演示，不代表真实后端状态。',
      at: '09:18',
    },
  ],
  'thread-preflight': [
    {
      id: 'msg-pre-1',
      role: 'user',
      content: '把 scripts/cleanup.sh 改成先 dry-run 再删除。',
      at: '18:12',
    },
    {
      id: 'msg-pre-2',
      role: 'assistant',
      content: '我会覆盖 scripts/cleanup.sh，先送审批。',
      at: '18:12',
      toolCalls: [executions[3].toolCalls[0]],
      approvalId: 'approval-cleanup-script',
    },
    {
      id: 'msg-pre-3',
      role: 'assistant',
      content:
        '审批已通过，但执行失败：目标文件在审批期间被修改，未写入。需要重新生成补丁。',
      at: '18:15',
    },
    {
      id: 'msg-pre-4',
      role: 'system',
      content: 'Demo 数据：这条记录专门演示「批准 ≠ 执行成功」。',
      at: '18:15',
    },
  ],
}

export function getDemoThread(threadId: string): DemoThread | undefined {
  return demoThreads.find((thread) => thread.id === threadId)
}

export function getDemoTask(taskId: string): DemoTask | undefined {
  return demoTasks.find((task) => task.id === taskId)
}

export function getDemoApproval(approvalId: string): DemoApproval | undefined {
  return demoApprovals.find((approval) => approval.id === approvalId)
}

export function getDemoExecution(
  taskId: string,
  executionId: string,
): DemoExecution | undefined {
  return executions.find(
    (execution) =>
      execution.taskId === taskId && execution.id === executionId,
  )
}

export function getDemoMessages(threadId: string): DemoMessage[] {
  return messagesByThread[threadId] ?? []
}

export function getDemoThreadTasks(threadId: string): DemoTask[] {
  return demoTasks.filter((task) => task.threadId === threadId)
}

export function getDemoThreadApprovals(threadId: string): DemoApproval[] {
  return demoApprovals
    .filter((approval) => approval.threadId === threadId)
    .sort((left, right) => {
      if (left.status === 'pending' && right.status !== 'pending') return -1
      if (left.status !== 'pending' && right.status === 'pending') return 1
      return 0
    })
}

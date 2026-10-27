# Codex 风格 UI Demo · 截图与体验说明

> 运行环境：Vite 8.3.5 dev server，1920×889，深色主题，Chrome/Playwright。
> 数据：`apps/desktop/src/frontend/src/demo/data.ts`，全部为 Demo 数据。
> 后端：**未启动、未调用**。
> 说明：`public/codex-demo.html` 是从 ZIP 解压出的原始静态原型；
> React 工作台已按该原型重构，截图来自 React 版本。

## 截图

| 文件 | 内容 |
|---|---|
| `screenshots/01-chat-pending.png` | 默认会话页：左侧最近会话、中央消息流、待审批卡片、输入框 |
| `screenshots/02-approval-card-pending.png` | 待审批卡片特写：工具、目标、风险、批准/拒绝 |
| `screenshots/03-audit-threads.png` | 审计页：按线程分组，显示审批数量、待审批数量、最近活动 |
| `screenshots/04-audit-approval-detail.png` | 审批详情：请求 → 用户决定 → 工具执行三段时间线（含「已批准但执行失败」） |

## 如何复现

```powershell
cd apps\desktop\src\frontend
npm install
npm run dev
```

打开：

```text
http://127.0.0.1:1420/#/chat/thread-lab-summary
http://127.0.0.1:1420/#/audit
http://127.0.0.1:1420/#/audit/thread-preflight/approval-cleanup-script
```

## 边界

- 所有会话、任务、审批、工具结果都是本地演示数据，页面有 `Demo 数据` 标识。
- 批准/拒绝只改变卡片本地状态，不会调用后端，也不会真正执行工具。
- 「已批准」与「执行成功」是不同状态；审批卡片不会把前者显示成后者。
- 真实 API、SSE、任务快照、Tauri 进程托管均未实现，见
  `docs/audit/2026-10-27-前端集成F0-整合审计.md` 与前端 README。

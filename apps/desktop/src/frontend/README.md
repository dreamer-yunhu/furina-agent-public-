# 芙宁娜 · 桌面前端（React + TypeScript + Vite + Tauri）

这是**桌面壳 + 界面**，不是业务逻辑所在。Python 侧（`apps/desktop/src/furina_desktop`）
仍然是 agent 引擎本体，监听 `127.0.0.1:8001`；本目录负责窗口、布局和会话界面。

## 当前状态（2026-10-27）

本轮在 F1 骨架上完成 **Codex 风格 UI Demo**，并按
`furina-codex-ui-demo.zip` 中的静态原型重构了视觉层（原 HTML 保留在
`public/codex-demo.html`，用于对照）：

- 左侧可折叠侧栏：新建会话、最近会话、任务、审计、设置。
- 中央会话工作区：消息流、工具调用状态、会话内审批卡片、输入框。
- 审批卡片：待审批更醒目；已处理默认折叠，可展开查看决定与工具执行结果。
- 审计页：按线程分组，线程 → 审批记录 → 审批详情三级导航。
- 任务页：任务列表、Execution 历史、关联审批。
- 详情面板：按需打开/关闭，窄屏改为浮层。
- 主题：默认浅色（对齐原型），支持跟随系统 / 深色；顶栏与设置页共用同一状态。
- 截图：`docs/demo/screenshots/`（会话页、待审批卡片、审计页、审批详情）。

**Demo 数据**：所有会话、任务、审批、工具结果都来自 `src/demo/data.ts`，页面上有
`Demo 数据` 标识。**不会调用后端，也不会触发真实工具执行。**

**尚未实现（不要误读）**：

- 不发送任何 HTTP 请求，不接 `POST /agent`、SSE、审批决定或恢复执行。
- 任务/审批查询仍无真实接口；Demo 数据不等于后端能力。
- Tauri 仍不托管 Python，没有角色独立窗口，没有双窗口同步。
- 没有事件总线、断线重连或快照轮询（属于 F2–F4）。

## 目录结构

```text
frontend/
├─ index.html
├─ src/
│  ├─ main.tsx
│  ├─ app/
│  │  ├─ App.tsx              路由 → 页面映射；侧栏/详情/主题 UI 状态
│  │  ├─ router.ts            hash 路由匹配（纯函数）
│  │  ├─ Link.tsx
│  │  └─ providers/           ThemeProvider + themeContext
│  ├─ layouts/                WorkbenchLayout + 六个插槽
│  ├─ pages/                  Chat / Tasks / TaskDetail / ExecutionDetail /
│  │                          Audit / AuditThread / AuditApprovalDetail /
│  │                          Approvals / ApprovalDetail / Settings / NotFound
│  ├─ features/
│  │  ├─ chat/                ConversationHeader / MessageList / ApprovalCard / Composer
│  │  ├─ navigation/          HeaderBar / SidebarNav
│  │  ├─ inspector/           RouteInspector
│  │  └─ shared/              statusMeta（状态文案与语气）
│  ├─ components/
│  │  ├─ ui/                  Panel / ContentSection / PageHeader / StatusPill /
│  │  │                       EmptyState / Notice / KeyValueList / Icon / IconButton
│  │  ├─ feedback/            ConnectionStatus
│  │  └─ placeholders/        背景与角色入口
│  ├─ demo/                   types.ts + data.ts（全部演示数据）
│  ├─ services/
│  │  ├─ api/config.ts        API 基址（F2 使用；当前只展示）
│  │  └─ desktop/windowRoles.ts  F4 双窗口适配缝（未接线）
│  ├─ hooks/useTheme.ts       主题读写
│  ├─ styles/                 tokens / theme / demo / index
│  ├─ assets/app/artwork.ts   美术资源集中入口
│  └─ test/setup.ts
├─ src-tauri/                 Tauri 2（本轮未改）
├─ vite.config.ts             端口固定 1420
└─ vitest.config.ts           jsdom 测试
```

## Demo 路由

| 路由 | 页面 |
|---|---|
| `#/chat` | 欢迎页 + 输入框 |
| `#/chat/thread-lab-summary` | 会话 + 待审批卡片 |
| `#/chat/thread-rag-recall` | 已处理审批（批准 / 拒绝） |
| `#/chat/thread-preflight` | 「已批准但执行失败」 |
| `#/tasks` | 任务列表 |
| `#/tasks/task-lab-summary` | 任务详情 + Execution 历史 |
| `#/audit` | 按线程分组的审计页 |
| `#/audit/thread-lab-summary` | 线程内审批记录 |
| `#/audit/thread-preflight/approval-cleanup-script` | 审批决策链 |
| `#/settings` | 主题与连接状态 |

## 常用命令

```powershell
cd apps\desktop\src\frontend

npm install            # 首次
npm run dev            # 只跑浏览器界面（不启 Tauri 窗口）
npm run build          # tsc 类型检查 + vite 产物到 dist/
npm run test           # vitest run（路由 / 导航 / 插槽 / 审批卡片）
npm run lint           # oxlint
npm run tauri:dev      # 起 Tauri 窗口（会自己拉起 vite dev server）
npm run build:backend  # 用 PyInstaller 把 Python 后端打成 exe（约 90s）
npm run tauri:build    # 出 NSIS 安装包（会把后端 exe 一并打进去）
npm run verify:release # 冒烟验收：断言页面来自内置资源，而不是 localhost 或错误页
npm run release        # 构建 + 验收（发布前只认这个入口）
```

> ⚠️ **不要用 `cargo build --release` 直接出包。** `custom-protocol` 是 Tauri 的
> 非默认 feature，`tauri build` 会自动带上；绕过 CLI 编出来的二进制是 dev 模式：
> 窗口正常打开，但 WebView2 加载的是 `http://localhost:1420`，没起 dev server
> 时显示 Edge 的 `ERR_CONNECTION_REFUSED` 页面。这个坑 2026-10-27 实际踩过一次，
> `npm run verify:release` 就是为它加的闸门。

## 设计约束

1. **路由使用 hash**。Tauri 生产环境从 `dist/` 加载，不假设服务端回退 `index.html`。
2. **布局与视觉解耦**：业务页面只用 `ContentSection`、`StatusPill` 等组件；
   颜色/间距/圆角改 `tokens.css` 与 `theme.css`。
3. **美术替换入口**：`src/assets/app/artwork.ts`。把图片放到 `src/assets/app/`，
   在 `artwork.ts` 里 import 并填入对应字段即可；没有资源时全部回退到中性占位/文字，
   不需要改业务组件：
   - `background`：工作台背景层
   - `character`：右下角角色入口
   - `logo`：侧栏品牌 Logo
   - `avatar`：侧栏用户头像 + 消息中的 Agent 头像
   - `emptyState`：空状态插图（任务/执行/404）
4. **Demo 数据与真实数据分离**：`src/demo/` 只服务演示；F2 接入真实 API 时另建
   `services/api` 类型与请求层，不能直接复用 Demo 类型。
5. **审批状态 ≠ 执行状态**：`demo/types.ts` 把 `status` 与 `toolExecutionStatus`
   分开；UI 不得把「已批准」显示成「执行成功」。
6. **不引入大型 UI 依赖**：图标为内联 SVG，路由为约 140 行的 hash 匹配。

## 与后端的关系（当前）

| 用途 | 端点 | 当前状态 |
|---|---|---|
| 健康检查 | `GET /healthz` | 后端已实现；前端未调用 |
| 对话（SSE） | `POST /agent` | 后端已实现；前端未接入 |
| 审批决定 | `POST /agent/decisions` | 后端已实现；前端未接入 |
| 审批恢复（SSE） | `POST /agent/resume` | 后端已实现；前端未接入 |
| 任务 / 执行 / 审批查询 | — | **后端尚未实现**（见 F0 审计） |

⚠️ Tauri 仍不会自动拉起 Python 服务；需要另开终端
`uv run --package furina-desktop python -m furina_desktop`。

## 测试边界

当前测试只覆盖纯前端：

- `src/app/router.test.ts`：路由匹配（含审计三级路由）。
- `src/app/App.test.tsx`：默认页、侧栏导航、审计导航、任务详情、404、根路径重定向、
  侧栏折叠、详情面板打开。
- `src/layouts/WorkbenchLayout.test.tsx`：插槽注入、Inspector 显隐、侧栏折叠。
- `src/features/chat/ApprovalCard.test.tsx`：批准/拒绝、折叠、状态区分。

**未运行**：后端/SSE 断连、任务生命周期、真实审批恢复、Tauri 双窗口。
这些属于 F2–F4，不能把 Demo 的绿灯当成业务链路已验证。

## 未完成的部分

- 真实任务、Execution、审批查询与轮询
- 真实 SSE 提交、token 渲染、审批决定与恢复
- 事件总线、断线重连、任务快照
- Tauri 进程托管、角色独立窗口、双窗口同步
- CSP 在 `tauri.conf.json` 里是 `null`，发布前必须收紧

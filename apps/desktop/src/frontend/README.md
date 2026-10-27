# 芙宁娜 · 桌面前端（React + TypeScript + Vite + Tauri）

这是**桌面壳 + 界面**，不是业务逻辑所在。Python 侧（`apps/desktop/src/furina_desktop`）
仍然是 agent 引擎本体，监听 `127.0.0.1:8001`；本目录负责窗口、布局和会话界面。

## F1 当前状态（2026-10-27）

已完成：工作台骨架、hash 路由、六个布局插槽、基础页面与空状态、中性设计令牌、
美术资源入口、路由导航测试。

**尚未实现（不要误读）**：

- 不发送任何 HTTP 请求，不生成模拟消息/任务/审批。
- 没有接入 `POST /agent`、SSE、审批决定或恢复执行。
- Tauri 仍不托管 Python，没有角色窗口，没有双窗口。
- 没有事件总线、断线重连或任务快照轮询（这些属于 F2–F4）。

## 目录结构

```text
frontend/
├─ index.html                 入口 HTML（Tauri 加载 vite build 的产物）
├─ src/
│  ├─ main.tsx                挂载点：只做 createRoot + 样式入口
│  ├─ app/
│  │  ├─ App.tsx              路由 → 页面映射；不读业务状态
│  │  ├─ router.ts            hash 路由匹配（纯函数）
│  │  └─ Link.tsx             内部链接
│  ├─ layouts/
│  │  ├─ WorkbenchLayout.tsx  Header / Sidebar / Main / Inspector 网格
│  │  ├─ HeaderSlot.tsx
│  │  ├─ SidebarSlot.tsx
│  │  ├─ MainWorkspaceSlot.tsx
│  │  ├─ InspectorSlot.tsx
│  │  ├─ BackgroundSlot.tsx
│  │  └─ CharacterSlot.tsx
│  ├─ pages/                  Chat / Tasks / TaskDetail / ExecutionDetail /
│  │                          Approvals / ApprovalDetail / Settings / NotFound
│  ├─ features/
│  │  ├─ navigation/          顶栏与侧栏导航
│  │  └─ inspector/           按路由显示详情面板
│  ├─ components/
│  │  ├─ ui/                  Panel / PageHeader / EmptyState / Notice / ...
│  │  ├─ feedback/            ConnectionStatus
│  │  └─ placeholders/        背景与角色占位
│  ├─ services/
│  │  ├─ api/config.ts        API 基址（F2 的 API Client 使用；F1 只展示）
│  │  └─ desktop/windowRoles.ts  F4 双窗口适配缝（当前未接线）
│  ├─ styles/
│  │  ├─ tokens.css           原始设计令牌
│  │  ├─ theme.css            语义主题（含浅色/深色）
│  │  ├─ layout.css           工作台网格与插槽
│  │  ├─ components.css       通用组件
│  │  ├─ pages.css            页面级布局
│  │  └─ index.css            样式入口
│  ├─ assets/app/artwork.ts   美术资源集中入口
│  └─ test/setup.ts           测试清理
├─ src-tauri/                 Rust 侧（Tauri 2，F1 未改）
│  ├─ Cargo.toml
│  ├─ src/lib.rs
│  ├─ src/main.rs
│  └─ tauri.conf.json         ⚠️ 窗口尺寸 / devUrl / 打包配置
├─ vite.config.ts             ⚠️ 端口固定 1420
└─ vitest.config.ts           测试配置（jsdom）
```

## 常用命令

```powershell
cd apps\desktop\src\frontend

npm install            # 首次
npm run dev            # 只跑浏览器界面（不启 Tauri 窗口）
npm run build          # tsc 类型检查 + vite 产物到 dist/
npm run test           # vitest run（路由 + 页面导航）
npm run lint           # oxlint
npm run tauri:dev      # 起 Tauri 窗口（会自己拉起 vite dev server）
npm run tauri:build    # 出安装包（msi / nsis），首次会下载 WiX 与 NSIS
```

## 设计约束

1. **路由使用 hash**（`#/tasks`）。Tauri 生产环境从 `dist/` 加载，不能假设
   服务端会对未知路径回退 `index.html`；hash 在 WebView 与浏览器里都稳定。
2. **端口 1420 是写死的**：`tauri.conf.json.build.devUrl` 指向它，
   `vite.config.ts` 用 `strictPort: true`，端口被占时直接报错而不是悄悄换端口。
3. **`dist/` 是 `tauri build` 的前端输入**：`tauri.conf.json.build.frontendDist = "../dist"`。
4. **布局与视觉解耦**：业务页面只使用 `Panel`、`PageHeader` 等组件；
   颜色/间距/圆角改 `tokens.css` 与 `theme.css`，不要写死到页面组件。
5. **美术替换入口**：`src/assets/app/artwork.ts`。没有资源时使用中性占位，
   不要提前锁定二次元视觉或引入未授权素材。
6. **窗口角色**：`services/desktop/windowRoles.ts` 只是 F4 的适配缝；
   当前只有 `main` 窗口，不要宣称已支持角色独立窗口。

## 与后端的关系（F1）

| 用途 | 端点 | 当前状态 |
|---|---|---|
| 健康检查 | `GET /healthz` | 后端已实现；前端未调用 |
| 对话（SSE） | `POST /agent` | 后端已实现；前端未接入 |
| 审批决定 | `POST /agent/decisions` | 后端已实现；前端未接入 |
| 审批恢复（SSE） | `POST /agent/resume` | 后端已实现；前端未接入 |
| 任务 / 执行 / 审批查询 | — | **后端尚未实现**（见 F0 审计） |

⚠️ 当前**没有**进程托管：Tauri 不会自动拉起 Python 服务，
需要另开终端 `uv run --package furina-desktop python -m furina_desktop`。
把后端做成 sidecar 属于 F4（见 `docs/TODO.md` T5 与
`docs/audit/2026-10-27-前端集成F0-整合审计.md`）。

## 测试边界

F1 的测试只覆盖纯前端：

- `src/app/router.test.ts`：hash 路由匹配、参数、未知路由。
- `src/app/App.test.tsx`：默认页、侧栏导航、任务详情参数、404、根路径重定向。

**没有运行**的后端/集成测试：SSE 断连、任务生命周期、审批决定与恢复、Tauri 双窗口。
这些分别属于 F2–F4，不能把 F1 的绿灯当成业务链路已验证。

## 未完成的部分

- 会话界面（消息列表 / 流式 token 渲染 / 审批卡片）
- 任务、执行、审批的真实查询与轮询
- `@tauri-apps/api` 的窗口控制、Python 进程托管
- CSP 在 `tauri.conf.json` 里是 `null`（开发期放行），发布前必须收紧
- 图标仍是 Tauri 默认图标

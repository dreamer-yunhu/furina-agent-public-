# 芙宁娜 · 桌面前端（React + TypeScript + Vite + Tauri）

这是**桌面壳 + 界面**，不是业务逻辑所在。Python 侧（`apps/desktop/src/furina_desktop`）
仍然是 agent 引擎本体，监听 `127.0.0.1:8001`；本目录只负责窗口和会话界面。

```
frontend/
├─ index.html            入口 HTML（Tauri 加载的就是 vite build 的产物）
├─ src/                  React 源码
│  ├─ main.tsx           挂载点
│  └─ App.tsx            当前是 Vite 模板示例，M0 阶段替换成会话界面
├─ src-tauri/            Rust 侧（Tauri 2）
│  ├─ Cargo.toml         crate 名 furina-desktop
│  ├─ src/lib.rs         窗口与插件装配（tauri::Builder）
│  ├─ src/main.rs        二进制入口
│  └─ tauri.conf.json    ⚠️ 窗口尺寸 / devUrl / 打包配置都在这里
└─ vite.config.ts        ⚠️ 端口固定 1420，别改（与 tauri.conf.json 的 devUrl 绑定）
```

## 常用命令

```powershell
cd apps\desktop\src\frontend

npm install            # 首次
npm run dev            # 只跑浏览器界面（不启 Tauri 窗口）
npm run build          # tsc 类型检查 + vite 产物到 dist/
npm run tauri:dev      # 起 Tauri 窗口（会自己拉起 vite dev server）
npm run tauri:build    # 出安装包（msi / nsis），首次会下载 WiX 与 NSIS
npm run lint           # oxlint
```

## 两个必须知道的约束

1. **端口 1420 是写死的**：`tauri.conf.json.build.devUrl` 指向它，
   `vite.config.ts` 用 `strictPort: true` 保证端口被占时直接报错而不是悄悄换端口
   —— 悄悄换端口的后果是 Tauri 窗口白屏，且很难看出原因。
2. **`dist/` 是 `tauri build` 的前端输入**：`tauri.conf.json.build.frontendDist = "../dist"`。
   改了输出目录要两处一起改。

## 与后端的关系（M0 阶段）

窗口里的界面通过 HTTP 打本机 FastAPI：

| 用途 | 端点 |
|---|---|
| 健康检查 | `GET  http://127.0.0.1:8001/healthz` |
| 对话（SSE） | `POST http://127.0.0.1:8001/agent` |
| 审批恢复（SSE） | `POST http://127.0.0.1:8001/agent/resume` |

⚠️ 当前**没有**做进程托管：Tauri 不会自动拉起 Python 服务，
需要另开终端 `uv run --package furina-desktop python -m furina_desktop`。
把后端做成 sidecar 是 M0 的待办（见 `docs/TODO.md`）。

## 未完成的部分

- 会话界面（消息列表 / 流式 token 渲染 / 审批卡片）仍是 Vite 模板示例
- 没有接 `@tauri-apps/api` 的任何能力（窗口控制、文件对话框等）
- CSP 在 `tauri.conf.json` 里是 `null`（开发期放行），发布前必须收紧
- 图标仍是 Tauri 默认图标

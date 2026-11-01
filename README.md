# 芙宁娜 Agent（furina-agent）

桌面优先的 AI 助手：**角色扮演对话 + 代码 Agent（带人工审批）**。

当前版本：**1.1.0**

## 下载安装（Windows）

| | |
|---|---|
| 安装包 | [`furina-desktop_1.1.0_x64-setup.exe`](https://github.com/dreamer-yunhu/furina-agent-public-/releases/latest) |
| 平台 | Windows 10 / 11 x64（WebView2 由安装器内置引导安装） |
| 大小 | 55.55 MiB |
| SHA-256 | `48c83a1a116d32f95ad3d5f93c7cbafdb70037be9af705918abcc94d46bd0abf` |

安装后双击启动即可：应用会自动拉起内置的 Python 后端，无需另外装 Python 或数据库。

**首次使用**：进入「设置」填写大模型密钥（存进 Windows 凭据管理器，不落明文文件），保存后应用会自动重启后端。

**排障位置**（出问题先看这里）：

```
%LOCALAPPDATA%\com.furina.desktop\logs\furina-desktop.log    # 应用与后端进程管理
%LOCALAPPDATA%\com.furina.desktop\logs\backend.stdout.log    # 后端 stdout
%LOCALAPPDATA%\com.furina.desktop\logs\backend.stderr.log    # 后端 stderr / 启动异常
%LOCALAPPDATA%\com.furina.desktop\backend\logs\desktop.log   # 后端启动阶段日志
```

## 仓库结构

```
furina-agent/
├─ packages/core/      furina_core —— 共享内核（零存储、零框架、零 LLM SDK）
├─ apps/web/           furina_web  —— Web 版（PostgreSQL + Redis）
├─ apps/desktop/       furina_desktop —— 桌面版（SQLite + LanceDB，双击即用）
├─ knowledge/          芙宁娜语料（32 文件 / 125 KB）
├─ scripts/            验证脚本；experiments/ 为归档实验
└─ docs/               规划、架构、审查与学习记录
```

> 旧单体 `backend/` 已于 2026-10-23 删除；现行代码只存在于 `apps/` 与 `packages/`。

## 快速开始

```powershell
cd C:\furina-agent
$env:UV_CACHE_DIR = "C:\furina-agent\.uv-cache"
$env:UV_PROJECT_ENVIRONMENT = "C:\furina-agent\.venv-build"
uv sync --all-packages --frozen

# 桌面版（监听 127.0.0.1:8001）
uv run --package furina-desktop python -m furina_desktop
```

启动后访问 `http://127.0.0.1:8001/healthz` 可看到 checkpoint / graph / 密钥配置状态。

> 需要 `.env` 提供 `base_url` / `api_key`。详见 [docs/WHITEPAPER.md](docs/WHITEPAPER.md) §8。

## 当前状态（2026-11-01）

| 能力 | 状态 |
|---|---|
| coder 子图 ReAct 循环 | ✅ 已实现 |
| HITL 审批（interrupt / resume） | ✅ 图内链路已通，有冒烟脚本 |
| 桌面 checkpoint（SQLite） | ✅ 已落地 |
| 主管图意图路由（CHAT / CODE） | ✅ 2026-10-26（Stage A）：模型产出 + 程序校验 + 有上限重试 |
| 主管图业务节点（画像/RAG/生成/持久化） | ⚠️ 仍是 `NotImplementedError`（非目标） |
| HTTP 流式桥（`POST /agent`） | ✅ 已实现（`subgraphs=True`，主管内部 token 不下发） |
| 审批恢复入口（`/agent/resume`） | ✅ 已实现（T23 链路，404/409 三判据） |
| 桌面进程托管 | ✅ Tauri 拉起并回收 Python 后端（Job Object 兜底强杀） |
| 启动可观测性 | ✅ 应用/子进程/后端三路日志落盘（1.1.0） |
| 前端数据接入 | ✅ 会话/任务/审计/审批全部走真实接口，**无演示数据** |
| 前端详情页 | ✅ 任务/执行/审计/审批详情已接后端（1.1.0 构建 2） |

## 必读文档

- [docs/WHITEPAPER.md](docs/WHITEPAPER.md) —— **开发白皮书**：架构、决策、契约
- [docs/PROGRESS.md](docs/PROGRESS.md) —— **开发进度记录**：时间线、已验证 / 未验证
- [docs/TODO.md](docs/TODO.md) —— **待办记录**：P0→P3，每条带验收判据
- [AGENTS.md](AGENTS.md) —— 仓库协作准则（先实测再断言）
- [docs/archive/](docs/archive/) —— 学习记录（本人阅读，不参与合并）

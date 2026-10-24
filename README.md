# 芙宁娜 Agent（furina-agent）

桌面优先的 AI 助手：**角色扮演对话 + 代码 Agent（带人工审批）**。

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

## 当前状态（2026-10-23）

| 能力 | 状态 |
|---|---|
| coder 子图 ReAct 循环 | ✅ 已实现 |
| HITL 审批（interrupt / resume） | ✅ 图内链路已通，有冒烟脚本 |
| 桌面 checkpoint（SQLite） | ✅ 已落地 |
| 主管图业务节点（画像/路由/RAG/生成/持久化） | ⚠️ 仍是 `NotImplementedError` |
| HTTP 流式桥（`POST /agent`） | ❌ `agent_stream` 未实现，当前必 500 |
| 审批恢复入口（`/agent/resume`） | ❌ 仍是 `pass` |
| 前端 | ❌ 脚手架 |

## 必读文档

- [docs/WHITEPAPER.md](docs/WHITEPAPER.md) —— **开发白皮书**：架构、决策、契约
- [docs/PROGRESS.md](docs/PROGRESS.md) —— **开发进度记录**：时间线、已验证 / 未验证
- [docs/TODO.md](docs/TODO.md) —— **待办记录**：P0→P3，每条带验收判据
- [AGENTS.md](AGENTS.md) —— 仓库协作准则（先实测再断言）
- [docs/archive/](docs/archive/) —— 学习记录（本人阅读，不参与合并）

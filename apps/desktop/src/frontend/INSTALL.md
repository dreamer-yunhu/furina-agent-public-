# 芙宁娜 Agent · Windows 安装说明

> 面向**拿到安装包的人**，不是面向开发者。开发相关的构建说明见 `README.md`。

---

## 一、当前版本能做什么（先说实话）

`0.1.0` 是**开发中的本地版**，能力边界如下：

| 能力 | 状态 |
|---|---|
| 连接本地后端（`127.0.0.1:8001`） | ✅ 启动时自动探测，顶栏显示「已连接 / 未连接 / 连接待检测」 |
| 侧栏「最近会话」 | ✅ 已连接时读真实数据库；未连接时回落到演示数据 |
| 读取已有会话的历史 | ✅ 已连接时从后端 checkpoint 汇总 |
| 发起对话、接收流式回复 | ✅ 已接入（`POST /agent` SSE） |
| 新建 / 重命名 / 删除会话 | ✅ 真实写后端 |
| **工具调用与审批** | ✅ 高风险写操作会弹真实审批卡（含 diff），批准后真的执行 |
| 后端运行时 | ✅ **已内置**（`binaries\furina-backend.exe`），目标机不需要装 Python |
| 任务页 / 审计页 | ✅ 读取真实 Task / 审批记录（支持状态过滤与搜索） |

两点必须说清楚：

1. **「已连接」只代表健康检查通过**（`/healthz`），不代表对话链路可用。
2. 界面上的「已批准」只代表点击了按钮，**不代表任务已执行**。

### 首次使用：配一个 API Key

打开应用 →「设置」→「模型密钥」，粘贴 `DEEPSEEK_API_KEY` 后点保存。

- 密钥存进 **Windows 凭据管理器**（控制面板 → 凭据管理器 → Windows 凭据，
  名称 `furina-agent`），**不写入任何配置文件**。
- 保存后应用会自动重启内置后端（约 5–10 秒），顶栏会短暂变「未连接」。
- 界面永远只显示尾号，不回显完整密钥。

> 兼容旧方式：也可以在 `%APPDATA%\furina-agent\.env` 放一行
> `DEEPSEEK_API_KEY=sk-...`（明文）。有凭据库时优先用凭据库。

没配 key 时应用**照样能打开**：顶栏显示「已连接」，但第一次对话会明确报错。
这是刻意设计的——起不来比报错更难查。

---

## 二、运行前提

| 项 | 要求 |
|---|---|
| 系统 | Windows 10 / 11，64 位 |
| WebView2 Runtime | 安装程序内置引导器，**缺失时会联网自动安装**；离线机器需自备 |
| 网络 | 仅首次安装且缺 WebView2 时需要 |
| 权限 | 当前用户安装，**不需要管理员权限** |

---

## 三、安装

1. 双击 `furina-desktop_0.1.0_x64-setup.exe`
2. 按向导完成（默认安装到当前用户目录）
3. 从开始菜单搜索「furina-desktop」启动

### 遇到 SmartScreen 拦截

当前安装包**未做代码签名**，Windows 会显示「Windows 已保护你的电脑」。

处理方式：点「更多信息」→「仍要运行」。

> 如果你是第一次从别人那里拿到这个包，请在运行前先核对第四节的 SHA-256。

---

## 四、产物校验

| 文件 | 大小 | SHA-256 |
|---|---|---|
| `furina-desktop_0.1.0_x64-setup.exe` | 50,725,666 B | `b12fe7443b98c61e6a2fdb09c36de5cd76f6ea620cfebfa022fa8d08cfabb1ec` |

> 体积从 3.8 MB 涨到 48.9 MB，是因为**后端运行时（Python + 依赖）已经打进包里**：
> `binaries\furina-backend.exe` 约 43 MB。这是"目标机不装 Python"必须付的代价。

校验命令（PowerShell）：

```powershell
Get-FileHash .\furina-desktop_0.1.0_x64-setup.exe -Algorithm SHA256
```

---

## 五、安装位置与数据

| 内容 | 路径 |
|---|---|
| 程序 | `%LOCALAPPDATA%\furina-desktop\` |
| 内置后端 | `%LOCALAPPDATA%\furina-desktop\binaries\furina-backend.exe` |
| 卸载程序 | `%LOCALAPPDATA%\furina-desktop\uninstall.exe` |
| 用户数据（WebView2 缓存、界面偏好） | `%LOCALAPPDATA%\com.furina.desktop\` |
| **后端数据**（SQLite 库、`data\`） | `%LOCALAPPDATA%\com.furina.desktop\backend\` |
| 用户配置（推荐的 `.env` 位置） | `%APPDATA%\furina-agent\.env` |
| 开始菜单快捷方式 | `%APPDATA%\Microsoft\Windows\Start Menu\Programs\furina-desktop.lnk` |
| 注册表卸载项 | `HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\furina-desktop` |

**卸载不会删除用户数据**（`com.furina.desktop` 与 `furina-agent` 都会保留）。需要彻底清理时手动删除。

---

## 六、卸载

- 设置 → 应用 → 已安装的应用 → 「furina-desktop」→ 卸载
- 或直接运行 `%LOCALAPPDATA%\furina-desktop\uninstall.exe`

---

## 七、常见问题

### 打开后是空白页，或显示「无法访问此页面 localhost」

说明拿到的是**开发构建**（打包时漏了 `custom-protocol` feature），不是正式包。
请重新走 `npm run release` 构建，该命令会带冒烟验收，能拦住这类产物。

### 双击没反应 / 进程立刻退出

常见原因是程序所在目录带 **Low 完整性标签**（例如放在某些沙箱工具管理的目录里），
WebView2 无法写入用户数据目录。把程序换到普通目录（如 `%LOCALAPPDATA%`）再试。

### 打不开 / 一直显示「连接待检测」

**第一次启动会慢**：内置后端是单文件打包，要先解压到临时目录，冷启动约 5–10 秒。
顶栏会先显示「连接待检测」，之后自动变「已连接」，不需要手动刷新。

如果超过半分钟还是「未连接」：

1. 打开任务管理器，看有没有 `furina-backend.exe` 在跑；
2. 没有的话，说明后端启动失败。数据目录 `%LOCALAPPDATA%\com.furina.desktop\backend\`
   下如果连 `data\` 都没生成，多半是杀毒软件拦了单文件 exe（PyInstaller 的已知误报）。

### 提示缺少 WebView2

安装程序会尝试联网安装；失败时手动安装：
<https://developer.microsoft.com/microsoft-edge/webview2/>

---

## 八、反馈

遇到问题请附上：安装包 SHA-256、Windows 版本、是否首次安装、现象截图。

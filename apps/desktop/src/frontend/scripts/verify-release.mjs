// ── AI-ASSISTED ── 本文件由 AI 生成，待人工复核 ──
//
// 发布包冒烟验收：断言「前端真的加载了」，而不是「窗口开出来了」。
//
// 背景（2026-10-27 事故）：target/release 里的 EXE 曾经是 dev 模式二进制
// （缺少 custom-protocol feature），双击后窗口正常出现，但 WebView2 实际加载
// 的是 http://localhost:1420 —— 没有 dev server 时显示 Edge 的
// ERR_CONNECTION_REFUSED 错误页。只看「窗口出现」永远发现不了这类静默失败。
//
// 复核重点：
//   1. 断言为什么是这几条 —— 见 assert-ish 段落，任何一条不满足都代表
//      「页面不是我们打包进去的那个应用」。
//   2. 为什么要先把 EXE 复制到临时目录再启动 —— 仓库目录带 Low 完整性标签，
//      在仓库内直接启动会 exit_code=101，那是环境问题不是产物问题，
//      不能让它污染验收结论。
//   3. CDP 端口是每次现找的空闲端口，避免和调试中的实例抢 9222。
//
// 用法:
//   node scripts/verify-release.mjs [path-to-exe]
//   npm run verify:release
//   npm run release            # 构建 + 验收

import { spawn, spawnSync } from 'node:child_process'
import fs from 'node:fs'
import net from 'node:net'
import os from 'node:os'
import path from 'node:path'

const DEFAULT_EXE = path.resolve(
  import.meta.dirname,
  '..',
  'src-tauri',
  'target',
  'release',
  'furina-desktop.exe',
)

const EXPECTED_ORIGIN = 'http://tauri.localhost'
const EXPECTED_TITLE = '芙宁娜'
const STARTUP_TIMEOUT_MS = 25_000

function fail(reason, detail) {
  console.error(`\n[FAIL] ${reason}`)
  if (detail) console.error(detail)
  process.exit(1)
}

function freePort() {
  return new Promise((resolve, reject) => {
    const srv = net.createServer()
    srv.unref()
    srv.on('error', reject)
    srv.listen(0, '127.0.0.1', () => {
      const { port } = srv.address()
      srv.close(() => resolve(port))
    })
  })
}

function killTree(pid) {
  if (!pid) return
  if (process.platform === 'win32') {
    spawnSync('taskkill', ['/PID', String(pid), '/T', '/F'], { stdio: 'ignore' })
  } else {
    try {
      process.kill(-pid, 'SIGKILL')
    } catch {
      /* 进程可能已退出 */
    }
  }
}

async function waitForTarget(port, deadline) {
  let lastError = 'no attempt made'
  let seen = []
  while (Date.now() < deadline) {
    try {
      const res = await fetch(`http://127.0.0.1:${port}/json`)
      const targets = await res.json()
      seen = targets.map((t) => `${t.type}:${t.url}`)
      // 启动早期会出现一个 about:blank 过渡 target，等真正的应用页
      const page = targets.find(
        (t) => t.type === 'page' && t.url && t.url !== 'about:blank',
      )
      if (page) return page
      lastError = 'CDP 已响应，但只有 about:blank'
    } catch (e) {
      lastError = e.message
    }
    await new Promise((r) => setTimeout(r, 400))
  }
  throw new Error(`等待 CDP 超时（${lastError}；已见目标: ${seen.join(', ') || '无'}）`)
}

async function readPageState(webSocketDebuggerUrl) {
  if (typeof WebSocket === 'undefined') {
    throw new Error('当前 Node 没有全局 WebSocket，需要 Node 22+')
  }
  const ws = new WebSocket(webSocketDebuggerUrl)
  return await new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      ws.close()
      reject(new Error('CDP Runtime.evaluate 超时'))
    }, 10_000)

    ws.onopen = () => {
      ws.send(
        JSON.stringify({
          id: 1,
          method: 'Runtime.evaluate',
          params: {
            expression: `({
              title: document.title,
              href: location.href,
              readyState: document.readyState,
              rootChildren: document.getElementById('root')?.children.length ?? -1,
              elements: document.querySelectorAll('*').length,
              textLength: (document.body.innerText || '').trim().length,
              head: (document.body.innerText || '').replace(/\\s+/g, ' ').slice(0, 120)
            })`,
            returnByValue: true,
          },
        }),
      )
    }
    ws.onmessage = (ev) => {
      const msg = JSON.parse(ev.data)
      if (msg.id !== 1) return
      clearTimeout(timer)
      ws.close()
      const value = msg.result?.result?.value
      if (!value) reject(new Error(`Runtime.evaluate 返回异常: ${JSON.stringify(msg)}`))
      else resolve(value)
    }
    ws.onerror = () => {
      clearTimeout(timer)
      reject(new Error('CDP WebSocket 连接失败'))
    }
  })
}

/**
 * 把 EXE 复制到临时目录再启动。
 * 仓库目录若带 Low 完整性标签，EXE 会继承它，WebView2 无法写 %LOCALAPPDATA%，
 * 进程会以 101 退出 —— 那是仓库环境问题，不该算到产物头上。
 */
function stageExe(exePath) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'furina-verify-'))
  const staged = path.join(dir, path.basename(exePath))
  fs.copyFileSync(exePath, staged)
  return { dir, staged }
}

async function main() {
  const exePath = path.resolve(process.argv[2] || DEFAULT_EXE)

  console.log('== 发布包冒烟验收 ==')
  console.log(`EXE: ${exePath}`)

  if (!fs.existsSync(exePath)) {
    fail('EXE 不存在', '先运行 `npm run tauri:build`（不要用 `cargo build --release`）')
  }

  const stat = fs.statSync(exePath)
  console.log(`大小: ${stat.size} B (${(stat.size / 1048576).toFixed(2)} MiB)`)

  const { dir, staged } = stageExe(exePath)
  const port = await freePort()
  console.log(`临时副本: ${staged}`)
  console.log(`CDP 端口: ${port}`)

  let child
  try {
    child = spawn(staged, [], {
      env: {
        ...process.env,
        WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS: `--remote-debugging-port=${port}`,
      },
      stdio: 'ignore',
    })

    const exitPromise = new Promise((resolve) => {
      child.once('exit', (code) => resolve(code))
    })

    let page
    try {
      page = await waitForTarget(port, Date.now() + STARTUP_TIMEOUT_MS)
    } catch (e) {
      const exited = await Promise.race([exitPromise, new Promise((r) => setTimeout(() => r(null), 100))])
      if (exited !== null) fail(`应用在页面就绪前退出，exit_code=${exited}`, e.message)
      fail('应用没有起来', e.message)
    }

    // 「有 page target」≠「应用页已经就绪」：
    //   · 启动早期会有一个 about:blank 过渡 target，随后还会换 target；
    //   · 文档要等 Tauri 拉起后端、挂载 React 之后才 complete。
    // 所以这里持续轮询：换 target + 等 readyState，直到拿到真实 URL 或超时。
    let currentTarget = page
    let state = await readPageState(currentTarget.webSocketDebuggerUrl)
    const readyDeadline = Date.now() + 15_000
    while (Date.now() < readyDeadline) {
      if (state.href !== 'about:blank' && state.readyState === 'complete') break
      await new Promise((r) => setTimeout(r, 300))
      try {
        const list = await (await fetch(`http://127.0.0.1:${port}/json`)).json()
        const next = list.find((t) => t.type === 'page' && t.url && t.url !== 'about:blank')
        if (next) currentTarget = next
      } catch {
        // CDP 短暂不可用：保持现有 target 继续重试
      }
      state = await readPageState(currentTarget.webSocketDebuggerUrl)
    }

    console.log('\n-- 页面状态 --')
    console.log(JSON.stringify(state, null, 2))

    // 断言：页面必须是我们打包进去的应用，而不是 Edge 错误页
    if (state.href.startsWith('chrome-error://')) {
      fail('加载的是浏览器错误页', `href=${state.href}\n多半是 EXE 用了 devUrl（dev 模式构建）`)
    }
    if (!state.href.startsWith(EXPECTED_ORIGIN)) {
      fail(
        `页面来源不是内置资源`,
        `期望以 ${EXPECTED_ORIGIN} 开头，实际 ${state.href}\n` +
          '这通常意味着构建时没有带上 custom-protocol feature —— 用 `npm run tauri:build` 重建',
      )
    }
    if (state.title !== EXPECTED_TITLE) {
      fail('页面标题不符', `期望「${EXPECTED_TITLE}」，实际「${state.title}」`)
    }
    if (state.readyState !== 'complete') {
      fail('文档尚未加载完成', `readyState=${state.readyState}`)
    }
    if (state.rootChildren < 1) {
      fail('React 根节点没有挂载', `#root 子元素数=${state.rootChildren}`)
    }
    if (state.textLength < 20) {
      fail('页面没有可读文本（疑似白屏）', `innerText 长度=${state.textLength}`)
    }

    console.log('\n[PASS] 前端资源已正确加载')
    console.log(`  标题: ${state.title}`)
    console.log(`  来源: ${state.href}`)
    console.log(`  元素: ${state.elements} 个，文本: ${state.textLength} 字符`)
    console.log(`  预览: ${state.head.slice(0, 80)}...`)
  } finally {
    killTree(child?.pid)
    // Windows 上进程退出与文件句柄释放之间有延迟，删除重试几次
    for (let attempt = 0; attempt < 5; attempt++) {
      await new Promise((r) => setTimeout(r, 400))
      try {
        fs.rmSync(dir, { recursive: true, force: true })
        break
      } catch (e) {
        if (attempt === 4) console.warn(`[warn] 临时目录未能删除（可能仍被占用）: ${dir} (${e.code})`)
      }
    }
  }
}

main().catch((e) => fail('验收脚本异常', e.stack || e.message))

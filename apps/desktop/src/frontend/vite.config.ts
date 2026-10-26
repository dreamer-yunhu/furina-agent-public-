import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
//
// ⚠️ Tauri 相关约束（改动前先读 tauri.conf.json）：
//   1. 端口必须固定 1420 —— tauri.conf.json 的 build.devUrl 写死这个地址，
//      端口一漂移，`tauri dev` 打开的就是白屏。
//   2. `clearScreen: false` 让 Tauri / cargo 的日志不被 Vite 清屏冲掉。
//   3. 不监听 src-tauri/** —— Rust 侧改动由 cargo 自己处理，
//      让 Vite 跟着重建只会白白触发整页重载。
const host = process.env.TAURI_DEV_HOST

export default defineConfig({
  plugins: [react()],
  clearScreen: false,
  server: {
    port: 1420,
    strictPort: true, // 被占用时直接报错，而不是悄悄换端口导致 Tauri 连不上
    host: host || false,
    hmr: host ? { protocol: 'ws', host, port: 1421 } : undefined,
    watch: {
      ignored: ['**/src-tauri/**'],
    },
  },
})

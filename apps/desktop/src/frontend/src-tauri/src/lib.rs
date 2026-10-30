// ── AI-ASSISTED ── 本文件由 AI 生成/改写，待人工复核 ──
// 复核重点：
//   1. 从 `.run(context)` 改成 `.build(context)` + `app.run(callback)`，
//      是因为后者才能拿到 `RunEvent::Exit` —— 没有它就没法在退出时回收后端进程。
//   2. 后端只"尽力"启动：找不到 venv 或启动失败都不该让应用打不开，
//      界面会显示"未连接"，比白屏可诊断。
//   3. ← D1.1 改动：日志插件 **debug 与 release 都注册**，写文件到
//      `%LOCALAPPDATA%\<identifier>\logs\`。原实现只在 debug 注册，
//      导致 release 版启动失败时一行日志都没有（D1 审计 R1）。
//      复核重点：release 下现在会持续写日志文件，注意磁盘占用
//      （已设 2MB 上限 + KeepOne 轮转）。
//   4. T6 的三个命令只做"凭据库 + 重启后端"，不碰任何业务逻辑；
//      密钥**从不回显**，status 只给尾号。

mod backend;
mod credentials;

use serde::Serialize;
use tauri::Manager;

#[derive(Serialize)]
struct KeyStatus {
    configured: bool,
    label: String,
    /// 密钥保存成功但后端没能重启时，把原因带回界面
    warning: Option<String>,
}

fn key_status(warning: Option<String>) -> KeyStatus {
    let (configured, label) = credentials::status();
    KeyStatus {
        configured,
        label,
        warning,
    }
}

#[tauri::command]
fn api_key_status() -> KeyStatus {
    key_status(None)
}

#[tauri::command]
fn save_api_key(app: tauri::AppHandle, key: String) -> Result<KeyStatus, String> {
    credentials::save_key(&key)?;
    // 密钥只在新进程的环境变量里生效，所以必须重启后端。
    // 重启失败不算致命：密钥已经安全存好，界面会显示 warning。
    let warning = backend::restart(&app).err();
    Ok(key_status(warning))
}

#[tauri::command]
fn clear_api_key(app: tauri::AppHandle) -> Result<KeyStatus, String> {
    credentials::clear_key()?;
    let warning = backend::restart(&app).err();
    Ok(key_status(warning))
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
  let app = tauri::Builder::default()
    .invoke_handler(tauri::generate_handler![
      api_key_status,
      save_api_key,
      clear_api_key
    ])
    .setup(|app| {
      // <- AI 改动（D1.1）：日志在 debug / release **都**写入文件。
      // 默认目标 = Stdout + LogDir；LogDir 在 Windows 上是
      //   %LOCALAPPDATA%\<bundle identifier>\logs\<package name>.log
      // 即 C:\Users\<用户>\AppData\Local\com.furina.desktop\logs\furina-desktop.log
      // 复核重点：① 轮转策略是 KeepOne + 2MB，超限会丢旧文件；
      //          ② 不要把日志目标改成 CWD 相对路径（安装目录可能不可写）。
      app.handle().plugin(
        tauri_plugin_log::Builder::default()
          .level(if cfg!(debug_assertions) {
            log::LevelFilter::Debug
          } else {
            log::LevelFilter::Info
          })
          .max_file_size(2 * 1024 * 1024)
          .timezone_strategy(tauri_plugin_log::TimezoneStrategy::UseLocal)
          // ← D1.1：凭据库的 DEBUG 日志会打印 service/user/target 名称。
          // 那些不算密钥，但属于"不该进产品日志的内部细节"，统一压到 WARN。
          .level_for("keyring", log::LevelFilter::Warn)
          .build(),
      )?;

      // <- AI 新增（D1.1）：每次启动留一条清晰的边界，便于在长日志里定位一次运行。
      // 时间戳由日志插件按本地时区打在行首，所以"本行时间 = Tauri 启动时间"。
      log::info!("══════════════════════════════════════════════════════════");
      log::info!(
        "Tauri 启动 profile={} version={}",
        if cfg!(debug_assertions) { "debug" } else { "release" },
        env!("CARGO_PKG_VERSION")
      );
      log::info!(
        "应用可执行文件: {}",
        std::env::current_exe()
          .map(|p| p.display().to_string())
          .unwrap_or_else(|e| format!("<取不到: {e}>"))
      );
      log::info!("进程 PID: {}", std::process::id());
      log::info!("══════════════════════════════════════════════════════════");

      // 拉起本地 Python 后端：优先安装包内置的 exe，开发环境回落到 .venv。
      // 已经在跑（端口被占）时不接管，退出时也不会去杀别人的进程。
      let child = backend::spawn_if_needed(app.handle());
      app.manage(backend::BackendProcess::new(child));

      Ok(())
    })
    .build(tauri::generate_context!())
    .expect("error while building tauri application");

  app.run(|handle, event| {
    if let tauri::RunEvent::Exit = event {
      // <- AI 改动（D1.1）：记录退出边界与状态查找结果。
      // 复核重点：这条日志出现但没有后面的"已停止"日志，说明状态没拿到，
      //          后端可能没被回收 —— 这正是要暴露的失败模式。
      log::info!("Tauri 退出事件 RunEvent::Exit");
      match handle.try_state::<backend::BackendProcess>() {
        Some(state) => backend::shutdown(&state.0),
        None => log::error!("退出时取不到 BackendProcess 状态，后端可能未被回收"),
      }
      log::info!("Tauri 退出流程结束");
    }
  });
}

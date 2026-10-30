// ── AI-ASSISTED ── 本文件由 AI 生成/改写，待人工复核 ──
//
// 本地 Python 后端的进程管理（T5 · 方案 A：开发环境）。
//
// 复核重点：
//   1. **只回收自己拉起的进程**。启动时如果 8001 已经被占用，说明后端是用户
//      自己开的（或上次没清理干净），此时不要接管、更不要在退出时杀掉它。
//      判据就是 `spawned: Option<Child>` —— None 表示不归我们管。
//   2. 判活用 TCP 连接而不是 HTTP：这里只需要知道"端口上有没有东西在听"。
//      真正的健康检查（checkpoint/graph/密钥）由前端请求 /healthz 负责，
//      两边职责不要混。
//   3. 仓库根来自 `CARGO_MANIFEST_DIR`，是**编译期**路径 —— 这意味着方案 A
//      的产物只能在本机构建、本机运行。换机器或发布包必须等 T4（打包）。
//      找不到 venv 入口时安静返回 None，由前端显示"未连接"，不要 panic。
//   4. `windows_subsystem = "windows"` 下没有控制台，子进程输出会丢；
//      排查后端启动失败要看它自己的日志，不是这里。

// ← D1.1 新增：可观测性（日志重定向 / 退出码监控 / HTTP 健康检查）。
// 本文件**只增加观测手段**，不改变进程托管的判定与生命周期策略：
//   · Job Object 的创建与 KILL_ON_JOB_CLOSE 语义未动；
//   · "只回收自己拉起的进程" 判据未动；
//   · 端口已占用时不接管的策略未动。
// 复核重点：
//   1. `FURINA_BACKEND_EXE` 是**诊断用**的覆盖开关，只在手工排障/验收时设置；
//      生产路径不会涉及。它不改变启动分支的判定顺序。
//   2. 退出码监控用的是**独立进程句柄**（OpenProcess），不碰 `Child`，
//      所以不会和 `wait()` 抢着回收子进程。

use std::fs::OpenOptions;
use std::io::{Read, Write};
use std::net::{SocketAddr, TcpStream};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Mutex;
use std::time::{Duration, Instant};

const BACKEND_HOST: &str = "127.0.0.1";
const BACKEND_PORT: u16 = 8001;

/// 健康检查总预算。onefile 形态冷启动实测约 6s，留足余量。
const READY_BUDGET_MS: u64 = 20_000;
/// 两次健康检查之间的间隔。
const PROBE_INTERVAL_MS: u64 = 500;
/// 单次 HTTP 请求的超时（连接 + 读）。
const PROBE_TIMEOUT_MS: u64 = 1_500;

/// 主动停止时置位；监控线程据此把退出码从"异常"降级为"预期"。
/// 全局单例是安全的：一个应用进程只托管一个后端。
static EXPECTED_EXIT: AtomicBool = AtomicBool::new(false);

/// 由 app 持有的子进程句柄。None = 后端不是本进程拉起的。
pub struct BackendProcess(pub Mutex<Option<Child>>);

impl BackendProcess {
    pub fn new(child: Option<Child>) -> Self {
        Self(Mutex::new(child))
    }
}

fn port_open() -> bool {
    let addr: SocketAddr = match format!("{BACKEND_HOST}:{BACKEND_PORT}").parse() {
        Ok(addr) => addr,
        Err(_) => return false,
    };
    TcpStream::connect_timeout(&addr, Duration::from_millis(300)).is_ok()
}

/// 在开发环境下定位仓库根：`<repo>/.venv/Scripts/furina-desktop.exe` 存在才算数。
fn dev_repo_root() -> Option<PathBuf> {
    // CARGO_MANIFEST_DIR = <repo>/apps/desktop/src/frontend/src-tauri
    let manifest_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let root = manifest_dir.ancestors().nth(5)?.to_path_buf();
    let launcher = root.join(".venv").join("Scripts").join("furina-desktop.exe");
    if launcher.is_file() {
        Some(root)
    } else {
        None
    }
}

/// 把子进程放进一个 "最后一个句柄关闭就杀光所有成员" 的 Job 里。
///
/// 为什么需要这一步：`shutdown()` 只在正常退出路径执行；应用被 taskkill /F、
/// 崩溃或被任务管理器结束时它根本不跑，后端就变成孤儿进程（端口还被占着，
/// 下次启动会误判"已经在跑"）。Job Object 把这条兜底交给内核。
///
/// 关键技巧：**故意泄漏 job 句柄**（`mem::forget`）。句柄随进程生命周期存在，
/// 进程怎么死的内核都会关闭它，从而触发 KILL_ON_JOB_CLOSE。
#[cfg(windows)]
fn adopt_in_kill_on_close_job(child: &Child) {
  use std::ffi::c_void;
  use std::os::windows::io::AsRawHandle;
  use windows_sys::Win32::Foundation::HANDLE;
  use windows_sys::Win32::System::JobObjects::{
    AssignProcessToJobObject, CreateJobObjectW, JobObjectExtendedLimitInformation,
    SetInformationJobObject, JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE,
    JOBOBJECT_EXTENDED_LIMIT_INFORMATION,
  };

  unsafe {
    let job = CreateJobObjectW(std::ptr::null(), std::ptr::null());
    if job.is_null() {
      log::warn!("创建 Job Object 失败，强杀兜底不可用");
      return;
    }

    let mut info: JOBOBJECT_EXTENDED_LIMIT_INFORMATION = std::mem::zeroed();
    info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;

    let set_ok = SetInformationJobObject(
      job,
      JobObjectExtendedLimitInformation,
      &info as *const _ as *const c_void,
      std::mem::size_of::<JOBOBJECT_EXTENDED_LIMIT_INFORMATION>() as u32,
    );
    if set_ok == 0 {
      log::warn!("设置 Job Object 限制失败，强杀兜底不可用");
      return;
    }

    // 子进程（以及它再派生的 python 进程，默认继承 job 成员身份）加入 job
    let assign_ok = AssignProcessToJobObject(job, child.as_raw_handle() as HANDLE);
    if assign_ok == 0 {
      log::warn!("把后端加入 Job Object 失败（可能已在不允许脱离的 job 里），强杀兜底不可用");
      return;
    }

    // 刻意**不调用 CloseHandle**：HANDLE 是裸指针、没有 Drop，
    // 句柄会一直留到进程结束；内核在进程死亡时关闭它 → 触发 KILL_ON_JOB_CLOSE。
    // （注意别用 mem::forget：HANDLE 是 Copy，那是空操作，只会招来编译器警告。）
    log::info!("后端已纳入 Job Object：应用被强杀时会被一并结束");
  }
}

#[cfg(not(windows))]
fn adopt_in_kill_on_close_job(_child: &Child) {}

// ══════════════════════════════════════════════════════════════════════
// 健康检查（← D1.1 新增）
// ══════════════════════════════════════════════════════════════════════

/// 发一次最小 HTTP GET，只关心状态码。
///
/// 为什么不用 reqwest：这里只需要"localhost 上拿一个状态码"，
/// 为此引入一整套 TLS/异步运行时（以及几十个传递依赖）不划算。
/// 手写 HTTP/1.1 的代价是：只支持明文、只支持 `Connection: close`、
/// 只解析状态行 —— 恰好覆盖 `GET /healthz` 的全部需求。
fn http_status(host: &str, port: u16, path: &str, timeout: Duration) -> Result<u16, String> {
    let addr: SocketAddr = format!("{host}:{port}")
        .parse()
        .map_err(|e| format!("地址解析失败: {e}"))?;

    let mut stream =
        TcpStream::connect_timeout(&addr, timeout).map_err(|e| format!("TCP 连接失败: {e}"))?;
    let _ = stream.set_read_timeout(Some(timeout));
    let _ = stream.set_write_timeout(Some(timeout));

    let request = format!(
        "GET {path} HTTP/1.1\r\nHost: {host}:{port}\r\nAccept: application/json\r\nConnection: close\r\n\r\n"
    );
    stream
        .write_all(request.as_bytes())
        .map_err(|e| format!("发送请求失败: {e}"))?;

    let mut response = String::new();
    stream
        .read_to_string(&mut response)
        .map_err(|e| format!("读取响应失败或超时: {e}"))?;

    let status_line = response
        .lines()
        .next()
        .ok_or_else(|| "响应为空".to_string())?;
    status_line
        .split_whitespace()
        .nth(1)
        .and_then(|code| code.parse::<u16>().ok())
        .ok_or_else(|| format!("无法解析状态行: {status_line:?}"))
}

/// 等后端真正就绪：**HTTP 200 才算 READY**。
///
/// ← D1.1 关键点：`port_open()` 只能说明"有东西在听"，一个启动到一半、
///   或干脆是别的程序占着 8001，都能让 TCP 连上。把 TCP 连通当成就绪，
///   就会把"没起来"报成"起来了"，这正是 D1 审计里 R5 描述的假象。
fn wait_until_ready(spawned_at: Instant) {
    std::thread::spawn(move || {
        let url = format!("http://{BACKEND_HOST}:{BACKEND_PORT}/healthz");
        log::info!(
            "健康检查开始 url={url} 预算={READY_BUDGET_MS}ms 间隔={PROBE_INTERVAL_MS}ms（后端已启动 {:?}）",
            spawned_at.elapsed()
        );

        let deadline = Instant::now() + Duration::from_millis(READY_BUDGET_MS);
        let mut attempt: u32 = 0;
        let mut last_reason = String::from("尚未发起探测");

        while Instant::now() < deadline {
            attempt += 1;
            let started = Instant::now();
            let result = http_status(
                BACKEND_HOST,
                BACKEND_PORT,
                "/healthz",
                Duration::from_millis(PROBE_TIMEOUT_MS),
            );

            match result {
                Ok(200) => {
                    log::info!(
                        "健康检查 #{attempt} GET {url} → HTTP 200，用时 {:?}；后端 READY（启动后 {:?}）",
                        started.elapsed(),
                        spawned_at.elapsed()
                    );
                    return;
                }
                Ok(code) => {
                    last_reason = format!("HTTP {code}（非 200）");
                    log::warn!(
                        "健康检查 #{attempt} GET {url} → HTTP {code}，用时 {:?}",
                        started.elapsed()
                    );
                }
                Err(err) => {
                    last_reason = err.clone();
                    log::warn!(
                        "健康检查 #{attempt} GET {url} → 失败：{err}，用时 {:?}",
                        started.elapsed()
                    );
                }
            }

            std::thread::sleep(Duration::from_millis(PROBE_INTERVAL_MS));
        }

        log::error!(
            "健康检查 FAILED：{url} 在 {READY_BUDGET_MS}ms 内未就绪（共 {attempt} 次），最后原因：{last_reason}"
        );
    });
}

/// 端口已被占用时只探一次，用于区分"端口通"与"后端就绪"。
fn probe_external_once() {
    let url = format!("http://{BACKEND_HOST}:{BACKEND_PORT}/healthz");
    match http_status(
        BACKEND_HOST,
        BACKEND_PORT,
        "/healthz",
        Duration::from_millis(PROBE_TIMEOUT_MS),
    ) {
        Ok(code) => log::info!("外部后端健康检查 GET {url} → HTTP {code}"),
        Err(err) => log::warn!("外部后端健康检查 GET {url} → 失败：{err}"),
    }
}

/// 监控子进程退出并记录退出码。
///
/// 为什么用 `OpenProcess` 而不是 `Child::try_wait`：
/// `Child` 被 `Mutex<Option<Child>>` 持有，监控线程若去抢锁会和
/// `restart()` / `shutdown()` 互相阻塞。这里**另开一个句柄**只做等待，
/// 与 `Child` 完全解耦，也就不可能与 `wait()` 抢回收。
#[cfg(windows)]
fn watch_exit(pid: u32, spawned_at: Instant) {
    std::thread::spawn(move || {
        use windows_sys::Win32::Foundation::{CloseHandle, WAIT_OBJECT_0, WAIT_TIMEOUT};
        use windows_sys::Win32::System::Threading::{
            GetExitCodeProcess, OpenProcess, WaitForSingleObject, PROCESS_QUERY_LIMITED_INFORMATION,
            PROCESS_SYNCHRONIZE,
        };

        let handle = unsafe {
            OpenProcess(
                PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_SYNCHRONIZE,
                0,
                pid,
            )
        };
        if handle.is_null() {
            log::warn!(
                "无法打开后端进程句柄 pid={pid}，退出码不可知（错误码 {}）",
                std::io::Error::last_os_error()
            );
            return;
        }

        loop {
            let wait = unsafe { WaitForSingleObject(handle, 500) };

            if wait == WAIT_OBJECT_0 {
                let mut code: u32 = 0;
                let ok = unsafe { GetExitCodeProcess(handle, &mut code) };
                let elapsed = spawned_at.elapsed();
                let expected = EXPECTED_EXIT.load(Ordering::SeqCst);

                if ok == 0 {
                    log::error!(
                        "后端进程已退出 pid={pid}，退出码读取失败（错误码 {}），运行时长 {elapsed:?}",
                        std::io::Error::last_os_error()
                    );
                } else if expected {
                    log::info!(
                        "后端进程已退出 pid={pid} 退出码={code} 运行时长={elapsed:?}（本应用主动停止）"
                    );
                } else {
                    log::error!(
                        "后端进程异常退出 pid={pid} 退出码={code} 运行时长={elapsed:?}（非本应用发起）"
                    );
                }

                unsafe { CloseHandle(handle) };
                return;
            }

            if wait != WAIT_TIMEOUT {
                log::warn!("等待后端进程失败 pid={pid} wait={wait}");
                unsafe { CloseHandle(handle) };
                return;
            }
        }
    });
}

#[cfg(not(windows))]
fn watch_exit(_pid: u32, _spawned_at: Instant) {}

/// 把子进程的 stdout / stderr 接到文件。
///
/// 为什么必须做：`windows_subsystem = "windows"` 下没有控制台，
/// PyInstaller bootloader 的报错、uvicorn 的启动失败、Python 的 traceback
/// 全部会掉进黑洞 —— D1 审计里"安装版起了但后端没起来、无从查起"就是这个原因。
/// 两个文件分开写，避免 stdout/stderr 交错破坏 traceback 的阅读顺序。
fn redirect_stdio(command: &mut Command, log_dir: &Path) {
    let stdout_path = log_dir.join("backend.stdout.log");
    let stderr_path = log_dir.join("backend.stderr.log");

    let open = |path: &Path| {
        OpenOptions::new()
            .create(true)
            .append(true)
            .open(path)
            .map_err(|e| format!("{}: {e}", path.display()))
    };

    match (open(&stdout_path), open(&stderr_path)) {
        (Ok(out), Ok(err)) => {
            command
                .stdout(Stdio::from(out))
                .stderr(Stdio::from(err));
            log::info!(
                "子进程输出重定向: stdout → {} ; stderr → {}",
                stdout_path.display(),
                stderr_path.display()
            );
        }
        (out, err) => {
            // 不静默：重定向失败意味着这次排障会失去子进程输出
            if let Err(e) = out {
                log::error!("打开 stdout 日志失败，子进程 stdout 将丢失：{e}");
            }
            if let Err(e) = err {
                log::error!("打开 stderr 日志失败，子进程 stderr 将丢失：{e}");
            }
        }
    }
}

fn spawn(exe: &Path, cwd: &Path, log_dir: &Path) -> Option<Child> {
    // 工作目录决定后端的 `data/` 落在哪：开发态必须是仓库根（沿用已有库），
    // 安装态必须是可写的用户数据目录（安装目录通常不可写）—— 这个坑实测踩过。
    log::info!("准备启动后端");
    log::info!(
        "  可执行文件: {}（存在={}）",
        exe.display(),
        exe.is_file()
    );
    log::info!("  工作目录:   {}（存在={}）", cwd.display(), cwd.is_dir());
    log::info!("  日志目录:   {}", log_dir.display());

    let mut command = Command::new(exe);
    command.current_dir(cwd);
    redirect_stdio(&mut command, log_dir);

    // T6：密钥从系统凭据库读，经**环境变量**下发给后端。
    // 环境变量只存在于进程内存，不落盘；后端 config.py 用 override=False 读 .env，
    // 所以这里注入的值优先级更高。
    // ← D1.1：**只记录有没有，不记录值**。
    match crate::credentials::load_key() {
        Some(key) => {
            command.env("DEEPSEEK_API_KEY", key);
            log::info!("  密钥: 已从系统凭据库注入（值不写日志）");
        }
        None => {
            // ← D1.1：这里**不能**断言"后端将无密钥" —— 凭据库只是两个来源之一，
            //    后端还会读 %APPDATA%\furina-agent\.env。实际值以它自己的启动横幅为准。
            log::warn!(
                "  密钥: 未从系统凭据库取到（若 .env 也未提供，后端会以 llm_key_configured=false 启动）"
            );
        }
    }

    let spawned_at = Instant::now();
    match command.spawn() {
        Ok(child) => {
            let pid = child.id();
            log::info!(
                "已启动本地后端 pid={pid}（spawn 调用耗时 {:?}）",
                spawned_at.elapsed()
            );
            adopt_in_kill_on_close_job(&child);
            watch_exit(pid, spawned_at);
            wait_until_ready(spawned_at);
            Some(child)
        }
        Err(err) => {
            log::error!(
                "启动本地后端失败: exe={} cwd={} kind={:?} raw_os_error={:?} err={err}",
                exe.display(),
                cwd.display(),
                err.kind(),
                err.raw_os_error()
            );
            None
        }
    }
}

/// 若后端未运行则拉起一个；返回的 Child 表示"这个进程归我们管"。
///
/// 查找顺序（T4 之后）：
///   ① 安装包内置的 `binaries/furina-backend.exe`（正式分发路径）
///   ② 开发仓库的 `.venv\Scripts\furina-desktop.exe`（方案 A 的兜底）
/// 日志目录：与 tauri-plugin-log 的 LogDir 目标同一个位置
/// （Windows 上是 `%LOCALAPPDATA%\<identifier>\logs`）。
/// 拿不到就退到系统临时目录 —— 宁可日志换个地方，也不能让启动因此失败。
fn resolve_log_dir(app: &tauri::AppHandle) -> PathBuf {
    use tauri::Manager;

    let dir = match app.path().app_log_dir() {
        Ok(dir) => dir,
        Err(err) => {
            let fallback = std::env::temp_dir().join("furina-desktop-logs");
            log::error!(
                "取不到应用日志目录（{err}），回退到 {}",
                fallback.display()
            );
            fallback
        }
    };
    if let Err(err) = std::fs::create_dir_all(&dir) {
        log::error!("创建日志目录失败（{}）: {err}", dir.display());
    }
    dir
}

/// 安装态的 CWD：`app_local_data_dir()/backend`。
fn packaged_cwd(app: &tauri::AppHandle) -> Option<PathBuf> {
    use tauri::Manager;

    match app.path().app_local_data_dir() {
        Ok(dir) => {
            let cwd = dir.join("backend");
            match std::fs::create_dir_all(&cwd) {
                Ok(()) => Some(cwd),
                Err(err) => {
                    log::error!("创建后端数据目录失败（{}）: {err}", cwd.display());
                    None
                }
            }
        }
        Err(err) => {
            log::error!("取不到应用数据目录: {err}");
            None
        }
    }
}

pub fn spawn_if_needed(app: &tauri::AppHandle) -> Option<Child> {
    use tauri::Manager;

    let log_dir = resolve_log_dir(app);

    // ── 诊断用覆盖开关（← D1.1）──────────────────────────────────────
    // 只用于验收"指定不存在的 exe / 秒退的 exe / 不提供 /healthz 的进程"。
    // 生产路径不设置这个变量；即使设置了，也仍然走同一个 spawn()，
    // 不改变任何托管语义。
    if let Ok(override_exe) = std::env::var("FURINA_BACKEND_EXE") {
        log::warn!("FURINA_BACKEND_EXE 生效，跳过内置/开发路径探测：{override_exe}");
        let cwd = packaged_cwd(app)
            .or_else(|| dev_repo_root())
            .unwrap_or_else(|| std::env::temp_dir());
        return spawn(Path::new(&override_exe), &cwd, &log_dir);
    }

    if port_open() {
        log::info!(
            "检测到 {BACKEND_HOST}:{BACKEND_PORT} 已有服务，跳过启动（退出时也不会杀它）"
        );
        // ← D1.1：端口通 ≠ 后端就绪，这里补一次真实的健康探测作为证据
        probe_external_once();
        return None;
    }

    log::info!("{BACKEND_HOST}:{BACKEND_PORT} 端口空闲，开始查找后端可执行文件");

    // ① 安装包内置
    match app.path().resource_dir() {
        Ok(resource_dir) => {
            let exe = resource_dir.join("binaries").join("furina-backend.exe");
            log::info!(
                "内置后端候选: {}（存在={}）",
                exe.display(),
                exe.is_file()
            );
            if exe.is_file() {
                let Some(cwd) = packaged_cwd(app) else {
                    return None;
                };
                return spawn(&exe, &cwd, &log_dir);
            }
        }
        Err(err) => {
            log::warn!("取不到 resource_dir: {err}");
        }
    }

    // ② 开发环境
    match dev_repo_root() {
        Some(root) => {
            let launcher = root.join(".venv").join("Scripts").join("furina-desktop.exe");
            log::info!(
                "开发态后端候选: {}（存在={}）",
                launcher.display(),
                launcher.is_file()
            );
            spawn(&launcher, &root, &log_dir)
        }
        None => {
            log::error!(
                "既没有内置后端（resource_dir 下无 binaries/furina-backend.exe），\
                 也不是开发环境（找不到 .venv/Scripts/furina-desktop.exe）—— 后端未启动"
            );
            None
        }
    }
}

/// 密钥变更后重启后端（凭据只在新进程的环境变量里生效）。
///
/// 只重启**自己拉起的**那一个：如果后端是用户手动开的，我们无权也不该杀它；
/// 此时返回 None，界面会提示"后端不是本应用启动的，需要手动重启"。
pub fn restart(app: &tauri::AppHandle) -> Result<(), String> {
    use tauri::Manager;

    let state = app
        .try_state::<BackendProcess>()
        .ok_or_else(|| "后端状态未初始化".to_string())?;

    let stopped_own_process = {
        let mut guard = state
            .0
            .lock()
            .map_err(|_| "后端状态锁中毒".to_string())?;
        match guard.take() {
            Some(mut child) => {
                stop(&mut child);
                true
            }
            None => false,
        }
    };

    if !stopped_own_process {
        // 端口上那个进程不是我们的：不杀、也不重启，交给用户
        if port_open() {
            log::warn!("重启后端被拒绝：端口已有非本应用启动的服务");
            return Err(
                "当前后端不是本应用启动的，请手动重启它后再保存密钥".to_string(),
            );
        }
    }
    log::info!("重启后端：旧进程已停止={stopped_own_process}");

    // 等端口释放（kill 后内核回收有延迟，立刻 spawn 会读到"端口已占用"而跳过）
    for _ in 0..30 {
        if !port_open() {
            break;
        }
        std::thread::sleep(Duration::from_millis(100));
    }

    let child = spawn_if_needed(app);
    let mut guard = state
        .0
        .lock()
        .map_err(|_| "后端状态锁中毒".to_string())?;
    *guard = child;
    Ok(())
}

/// 结束后端进程**及其子进程**。
///
/// ⚠️ 只 kill 父进程是不够的：开发态拉起的 `.venv\Scripts\furina-desktop.exe`
/// 是个 launcher，真正跑 uvicorn 的是它派生的 python.exe。只杀 launcher 会留下
/// 孤儿 python 继续占着 8001 —— 实测导致"重启后端口仍被占用、状态跟踪错乱"。
/// Windows 上用 `taskkill /T` 杀整棵树。
fn stop(process: &mut Child) {
    let pid = process.id();
    let started = Instant::now();
    // ← D1.1：先置位，让退出码监控线程把这次退出标成"预期"而不是"异常"
    EXPECTED_EXIT.store(true, Ordering::SeqCst);
    log::info!("正在停止后端 pid={pid}（Windows 上用 taskkill /T /F 结束整棵进程树）");

    #[cfg(windows)]
    {
        let pid_arg = pid.to_string();
        match Command::new("taskkill")
            .args(["/PID", &pid_arg, "/T", "/F"])
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .status()
        {
            Ok(status) => log::info!("taskkill 返回: {status:?}"),
            Err(err) => log::error!("执行 taskkill 失败: {err}"),
        }
    }
    #[cfg(not(windows))]
    {
        if let Err(err) = process.kill() {
            log::error!("kill 失败 pid={pid}: {err}");
        }
    }

    // 必须 wait，否则 Windows 上留下僵尸句柄
    match process.wait() {
        Ok(status) => log::info!(
            "后端进程已回收 pid={pid} 退出码={:?}（本应用发起，耗时 {:?}）",
            status.code(),
            started.elapsed()
        ),
        Err(err) => log::error!("等待后端退出失败 pid={pid}: {err}"),
    }
}

/// 应用退出时调用：只杀自己拉起的那一个。
pub fn shutdown(child: &Mutex<Option<Child>>) {
    let mut guard = match child.lock() {
        Ok(guard) => guard,
        Err(poisoned) => poisoned.into_inner(),
    };
    if let Some(mut process) = guard.take() {
        let pid = process.id();
        log::info!("退出流程：后端由本应用启动 pid={pid}，开始回收");
        stop(&mut process);
        log::info!("已停止本地后端 pid={pid}");
    } else {
        log::info!("退出流程：没有需要回收的后端（未由本应用启动，或从未启动）");
    }
}

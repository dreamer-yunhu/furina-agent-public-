// ── AI-ASSISTED ── 本文件由 AI 生成/改写，待人工复核 ──
//
// API 密钥存储（T6）。用系统凭据库，不落明文文件。
//
// 复核重点：
//   1. **密钥只存在凭据管理器里**：磁盘上（.env / 配置文件）不应再有明文。
//      保存后由 `backend::restart()` 重新拉起后端，通过**环境变量**下发；
//      进程环境只活在内存里，不写盘。
//   2. `status()` 只回尾号，**绝不回显完整密钥** —— 界面上泄露一次就等于泄露。
//   3. 删除是幂等的：凭据本来就不存在（NoEntry）也算成功，否则前端"清除"按钮
//      会在第二次点击时报错。
//   4. Windows 上走 Credential Manager（凭据管理器 → Windows 凭据）。

use keyring::Entry;

const SERVICE: &str = "furina-agent";
const ACCOUNT: &str = "deepseek-api-key";

fn entry() -> Result<Entry, String> {
    Entry::new(SERVICE, ACCOUNT).map_err(|err| format!("无法访问系统凭据库: {err}"))
}

/// 读取密钥；没有或为空都返回 None。
pub fn load_key() -> Option<String> {
    let entry = entry().ok()?;
    match entry.get_password() {
        Ok(value) if !value.trim().is_empty() => Some(value),
        _ => None, // NoEntry / 读失败：一律当作"没配置"，不让启动失败
    }
}

pub fn save_key(key: &str) -> Result<(), String> {
    let key = key.trim();
    if key.len() < 8 {
        return Err("密钥长度过短，疑似粘贴不完整".to_string());
    }
    entry()?
        .set_password(key)
        .map_err(|err| format!("写入系统凭据库失败: {err}"))
}

pub fn clear_key() -> Result<(), String> {
    match entry()?.delete_credential() {
        Ok(()) => Ok(()),
        Err(keyring::Error::NoEntry) => Ok(()),
        Err(err) => Err(format!("删除系统凭据失败: {err}")),
    }
}

/// 给界面看的状态：只暴露"配没配"和尾号。
pub fn status() -> (bool, String) {
    match load_key() {
        Some(key) => {
            let tail: String = key.chars().rev().take(4).collect::<Vec<_>>().into_iter().rev().collect();
            (true, format!("已保存 · 尾号 {tail}"))
        }
        None => (false, "未配置".to_string()),
    }
}

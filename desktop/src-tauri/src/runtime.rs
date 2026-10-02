use std::fs;
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::time::{Duration, Instant};

#[cfg(windows)]
use std::os::windows::process::CommandExt;

#[cfg(windows)]
const CREATE_NO_WINDOW: u32 = 0x08000000;

/// Map bind hosts to a browser-openable local host.
/// Matches `_host_for_local_browser` in `nanobot/cli/webui_support.py`.
pub fn format_local_host(host: &str) -> String {
    let trimmed = host.trim();
    if trimmed == "0.0.0.0" || trimmed.is_empty() {
        "127.0.0.1".to_string()
    } else if trimmed == "::" {
        "[::1]".to_string()
    } else if trimmed.contains(':') && !trimmed.starts_with('[') {
        format!("[{trimmed}]")
    } else {
        trimmed.to_string()
    }
}

/// Generate the bootstrap URL for the WebUI.
/// Matches `_webui_browser_url` in `nanobot/cli/webui_support.py`.
pub fn bootstrap_url(host: &str, port: u16, secret: &str) -> String {
    let clean_host = format_local_host(host);
    let base_url = format!("http://{clean_host}:{port}");
    let trimmed_secret = secret.trim();
    if trimmed_secret.is_empty() {
        base_url
    } else {
        format!(
            "{base_url}/#/?bootstrapSecret={}",
            urlencoding::encode(trimmed_secret)
        )
    }
}

/// Resolves the Python executable to run.
///
/// Resolves the Python executable to run.
///
/// Priority:
/// 1. `NANOBOT_DESKTOP_PYTHON` environment variable (used during development).
/// 2. Bundled python in `<resource_dir>/runtime/python/...` or adjacent runtime directories.
pub fn resolve_python(resource_dir: Option<&Path>) -> Result<PathBuf, String> {
    if let Ok(val) = std::env::var("NANOBOT_DESKTOP_PYTHON") {
        let trimmed = val.trim();
        if !trimmed.is_empty() {
            let path = PathBuf::from(trimmed);
            if path.is_file() {
                return Ok(path);
            }
            return Err(format!(
                "NANOBOT_DESKTOP_PYTHON was set to '{trimmed}', but the file does not exist."
            ));
        }
    }

    let mut candidate_bases: Vec<PathBuf> = Vec::new();

    if let Some(res_dir) = resource_dir {
        candidate_bases.push(res_dir.to_path_buf());
    }

    if let Ok(exe) = std::env::current_exe() {
        if let Some(parent) = exe.parent() {
            candidate_bases.push(parent.to_path_buf());
            if let Some(grandparent) = parent.parent() {
                candidate_bases.push(grandparent.to_path_buf());
            }
        }
    }

    if let Ok(cwd) = std::env::current_dir() {
        candidate_bases.push(cwd.join("desktop"));
        candidate_bases.push(cwd);
    }

    #[cfg(windows)]
    let rel_paths = [
        "runtime/python/python.exe",
        "python/python.exe",
        "resources/runtime/python/python.exe",
    ];

    #[cfg(not(windows))]
    let rel_paths = [
        "runtime/python/bin/python3",
        "python/bin/python3",
        "resources/runtime/python/bin/python3",
    ];

    for base in candidate_bases {
        for rel in &rel_paths {
            let candidate = base.join(rel);
            if candidate.is_file() {
                return Ok(candidate);
            }
        }
    }

    Err(
        "Could not find Python interpreter.\n\
         In development: set the NANOBOT_DESKTOP_PYTHON environment variable to your venv's python executable.\n\
         In production: ensure the runtime bundle is installed in the app resources directory."
            .to_string(),
    )
}

/// Resolves the Nanobot config path.
/// Defaults to `NANOBOT_DESKTOP_CONFIG` or `~/.nanobot/config.json`.
pub fn resolve_config_path() -> PathBuf {
    if let Ok(val) = std::env::var("NANOBOT_DESKTOP_CONFIG") {
        let trimmed = val.trim();
        if !trimmed.is_empty() {
            return PathBuf::from(trimmed);
        }
    }

    let home = std::env::var("USERPROFILE")
        .or_else(|_| std::env::var("HOME"))
        .unwrap_or_else(|_| ".".to_string());

    PathBuf::from(home).join(".nanobot").join("config.json")
}

/// Reads the WebSocket channel endpoint from `config.json`.
/// Returns `Some((host, port, secret))` if readable, or None if the file doesn't exist / isn't valid JSON.
pub fn read_webui_endpoint(config_path: &Path) -> Option<(String, u16, String)> {
    let content = fs::read_to_string(config_path).ok()?;
    let value: serde_json::Value = serde_json::from_str(&content).ok()?;

    // Read channels.websocket
    let channels = value.get("channels")?;
    let ws = channels.get("websocket").or_else(|| channels.get("WebSocket"))?;

    let host = ws
        .get("host")
        .and_then(|h| h.as_str())
        .unwrap_or("127.0.0.1")
        .to_string();

    let port = ws
        .get("port")
        .and_then(|p| p.as_u64())
        .unwrap_or(8765) as u16;

    let secret = ws
        .get("tokenIssueSecret")
        .or_else(|| ws.get("token_issue_secret"))
        .or_else(|| ws.get("token"))
        .and_then(|s| s.as_str())
        .unwrap_or("")
        .to_string();

    Some((host, port, secret))
}

/// Spawns the Nanobot sidecar process: `python -m nanobot webui --no-open --yes`.
pub fn spawn_sidecar(
    python: &Path,
    custom_config: Option<&Path>,
    workspace: Option<&Path>,
    resource_dir: Option<&Path>,
    log_file: &Path,
) -> Result<Child, String> {
    if let Some(parent) = log_file.parent() {
        fs::create_dir_all(parent).map_err(|e| {
            format!(
                "Failed to create directory for log file '{}': {}",
                parent.display(),
                e
            )
        })?;
    }

    let out_file = fs::OpenOptions::new()
        .create(true)
        .write(true)
        .truncate(true)
        .open(log_file)
        .map_err(|e| format!("Failed to open log file '{}': {}", log_file.display(), e))?;

    let err_file = out_file
        .try_clone()
        .map_err(|e| format!("Failed to duplicate log file descriptor: {e}"))?;

    let mut cmd = Command::new(python);
    cmd.args(["-m", "nanobot", "webui", "--no-open", "--yes"]);

    if let Some(cfg) = custom_config {
        cmd.args(["--config", &cfg.to_string_lossy()]);
    }

    if let Some(ws) = workspace {
        cmd.args(["--workspace", &ws.to_string_lossy()]);
    } else if let Ok(val) = std::env::var("NANOBOT_DESKTOP_WORKSPACE") {
        if !val.trim().is_empty() {
            cmd.args(["--workspace", val.trim()]);
        }
    }

    cmd.env("PYTHONUNBUFFERED", "1");

    // In production, configure PYTHONPATH to point to bundled site-packages
    let mut site_packages_opt: Option<PathBuf> = None;
    if let Some(res_dir) = resource_dir {
        let p = res_dir.join("runtime").join("site-packages");
        if p.is_dir() {
            site_packages_opt = Some(p);
        }
    }
    if site_packages_opt.is_none() {
        if let Some(parent) = python.parent() {
            if let Some(grandparent) = parent.parent() {
                let p = grandparent.join("site-packages");
                if p.is_dir() {
                    site_packages_opt = Some(p);
                }
            }
        }
    }
    if let Some(sp) = site_packages_opt {
        cmd.env("PYTHONPATH", sp);
    }

    cmd.stdin(Stdio::null());
    cmd.stdout(Stdio::from(out_file));
    cmd.stderr(Stdio::from(err_file));

    #[cfg(windows)]
    cmd.creation_flags(CREATE_NO_WINDOW);

    cmd.spawn()
        .map_err(|e| format!("Failed to spawn Nanobot sidecar process: {e}"))
}

use std::sync::{Arc, Mutex};

/// Polls until the Nanobot WebUI gateway responds with 200 OK at `/webui/bootstrap`,
/// or until timeout.
pub fn wait_ready(
    config_path: &Path,
    log_path: &Path,
    sidecar: &Arc<Mutex<Option<Child>>>,
    timeout: Duration,
) -> Result<(String, u16, String), String> {
    let start = Instant::now();
    let poll_interval = Duration::from_millis(300);

    while start.elapsed() < timeout {
        // 1. Check if the child process exited prematurely
        if let Ok(mut guard) = sidecar.lock() {
            if let Some(proc) = guard.as_mut() {
                match proc.try_wait() {
                    Ok(Some(status)) => {
                        // Check if the launch log contains a known port conflict
                        if let Ok(log_text) = fs::read_to_string(log_path) {
                            let lower = log_text.to_lowercase();
                            if lower.contains("conflict") || lower.contains("already in use") {
                                return Err(format!(
                                    "Port conflict detected: Another process is already using the configured WebUI port.\n\
                                     Try running 'nanobot gateway status' or 'nanobot gateway stop' to stop conflicting instances.\n\
                                     Details in log: {}",
                                    log_path.display()
                                ));
                            }
                        }

                        return Err(format!(
                            "Nanobot sidecar exited unexpectedly with status: {status}.\n\
                             Please inspect the launch log for details:\n{}",
                            log_path.display()
                        ));
                    }
                    Ok(None) => {
                        // Still running, proceed
                    }
                    Err(e) => {
                        return Err(format!("Failed to query sidecar status: {e}"));
                    }
                }
            }
        }

        // 2. Try to read the endpoint from config
        if let Some((host, port, secret)) = read_webui_endpoint(config_path) {
            let clean_host = format_local_host(&host);
            let probe_url = format!("http://{clean_host}:{port}/webui/bootstrap");

            let mut req = ureq::get(&probe_url).timeout(Duration::from_millis(1500));
            if !secret.trim().is_empty() {
                req = req.set("X-Nanobot-Auth", secret.trim());
            }

            match req.call() {
                Ok(resp) if resp.status() == 200 => {
                    return Ok((host, port, secret));
                }
                Ok(_) | Err(_) => {
                    // Gateway not listening or not ready yet, continue polling
                }
            }
        }

        std::thread::sleep(poll_interval);
    }

    // Check if the port was open but rejected auth (port conflict or wrong gateway)
    if let Some((host, port, _)) = read_webui_endpoint(config_path) {
        let clean_host = format_local_host(&host);
        use std::net::ToSocketAddrs;
        let is_port_open = format!("{clean_host}:{port}")
            .to_socket_addrs()
            .ok()
            .and_then(|mut addrs| addrs.next())
            .map(|addr| std::net::TcpStream::connect_timeout(&addr, Duration::from_millis(500)).is_ok())
            .unwrap_or(false);

        if is_port_open {
            return Err(format!(
                "Port conflict detected on port {port}: The port is open, but did not respond with valid bootstrap credentials.\n\
                 Another process or older gateway may be occupying this port.\n\
                 Try running 'nanobot gateway status' or 'nanobot gateway stop'.\n\
                 Details in log: {}",
                log_path.display()
            ));
        }
    }

    // Also check if launch log recorded a port conflict before timeout
    if let Ok(log_text) = fs::read_to_string(log_path) {
        let lower = log_text.to_lowercase();
        if lower.contains("conflict") || lower.contains("already in use") {
            return Err(format!(
                "Port conflict detected: The configured port is already occupied.\n\
                 Try running 'nanobot gateway status' or 'nanobot gateway stop'.\n\
                 Details in log: {}",
                log_path.display()
            ));
        }
    }

    Err(format!(
        "Timed out waiting for Nanobot gateway to become ready after {}s.\n\
         Please inspect the launch log for details:\n{}",
        timeout.as_secs(),
        log_path.display()
    ))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_format_local_host() {
        assert_eq!(format_local_host("0.0.0.0"), "127.0.0.1");
        assert_eq!(format_local_host(""), "127.0.0.1");
        assert_eq!(format_local_host("::"), "[::1]");
        assert_eq!(format_local_host("::1"), "[::1]");
        assert_eq!(format_local_host("[::1]"), "[::1]");
        assert_eq!(format_local_host("127.0.0.1"), "127.0.0.1");
        assert_eq!(format_local_host("localhost"), "localhost");
    }

    #[test]
    fn test_bootstrap_url() {
        assert_eq!(
            bootstrap_url("127.0.0.1", 8765, ""),
            "http://127.0.0.1:8765"
        );
        assert_eq!(
            bootstrap_url("0.0.0.0", 8765, "simple-secret"),
            "http://127.0.0.1:8765/#/?bootstrapSecret=simple-secret"
        );
        assert_eq!(
            bootstrap_url("127.0.0.1", 8765, "abc/def?foo=bar&baz=123 hello"),
            "http://127.0.0.1:8765/#/?bootstrapSecret=abc%2Fdef%3Ffoo%3Dbar%26baz%3D123%20hello"
        );
    }

    #[test]
    fn test_read_webui_endpoint_camel_case() {
        let temp_dir = std::env::temp_dir();
        let test_file = temp_dir.join("test_config_camel.json");
        let content = r#"{
            "channels": {
                "websocket": {
                    "enabled": true,
                    "host": "0.0.0.0",
                    "port": 9000,
                    "tokenIssueSecret": "my-secret-token"
                }
            }
        }"#;
        fs::write(&test_file, content).unwrap();

        let endpoint = read_webui_endpoint(&test_file).expect("Failed to read endpoint");
        assert_eq!(endpoint.0, "0.0.0.0");
        assert_eq!(endpoint.1, 9000);
        assert_eq!(endpoint.2, "my-secret-token");

        let _ = fs::remove_file(test_file);
    }

    #[test]
    fn test_read_webui_endpoint_snake_case() {
        let temp_dir = std::env::temp_dir();
        let test_file = temp_dir.join("test_config_snake.json");
        let content = r#"{
            "channels": {
                "websocket": {
                    "enabled": true,
                    "host": "127.0.0.1",
                    "port": 8765,
                    "token_issue_secret": "snake-secret"
                }
            }
        }"#;
        fs::write(&test_file, content).unwrap();

        let endpoint = read_webui_endpoint(&test_file).expect("Failed to read endpoint");
        assert_eq!(endpoint.0, "127.0.0.1");
        assert_eq!(endpoint.1, 8765);
        assert_eq!(endpoint.2, "snake-secret");

        let _ = fs::remove_file(test_file);
    }

    #[test]
    fn test_wait_ready_port_conflict_in_log() {
        let temp_dir = std::env::temp_dir();
        let log_file = temp_dir.join("test_conflict.log");
        fs::write(&log_file, "ERROR: address already in use on port 18790").unwrap();
        let config_file = temp_dir.join("test_nonexistent_config.json");

        let sidecar_state = Arc::new(Mutex::new(None));
        let res = wait_ready(
            &config_file,
            &log_file,
            &sidecar_state,
            Duration::from_millis(100),
        );

        assert!(res.is_err());
        let err_msg = res.unwrap_err();
        assert!(err_msg.contains("Port conflict detected"));

        let _ = fs::remove_file(log_file);
    }

    #[test]
    fn test_wait_ready_open_port_without_auth() {
        use std::net::TcpListener;
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let port = listener.local_addr().unwrap().port();

        let temp_dir = std::env::temp_dir();
        let log_file = temp_dir.join("test_open_port.log");
        fs::write(&log_file, "Starting...").unwrap();

        let config_file = temp_dir.join("test_open_port_config.json");
        let content = format!(
            r#"{{
                "channels": {{
                    "websocket": {{
                        "enabled": true,
                        "host": "127.0.0.1",
                        "port": {port},
                        "tokenIssueSecret": "secret"
                    }}
                }}
            }}"#
        );
        fs::write(&config_file, content).unwrap();

        let sidecar_state = Arc::new(Mutex::new(None));
        let res = wait_ready(
            &config_file,
            &log_file,
            &sidecar_state,
            Duration::from_millis(150),
        );

        assert!(res.is_err());
        let err_msg = res.unwrap_err();
        assert!(err_msg.contains("Port conflict detected on port"));

        let _ = fs::remove_file(log_file);
        let _ = fs::remove_file(config_file);
    }
}


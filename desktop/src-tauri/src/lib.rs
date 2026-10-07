pub mod runtime;

use std::path::PathBuf;
use std::process::Child;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::time::Duration;
use tauri::{Manager, RunEvent, Url, WebviewUrl, WebviewWindowBuilder};

/// Set once the exit sequence starts, so a re-entrant `ExitRequested` (from our own `exit()`)
/// is allowed through instead of being prevented again.
static SHUTTING_DOWN: AtomicBool = AtomicBool::new(false);

pub struct AppState {
    pub sidecar: Arc<Mutex<Option<Child>>>,
    pub log_path: PathBuf,
}

#[tauri::command]
fn open_log_file(app: tauri::AppHandle) -> Result<(), String> {
    let state = app.state::<AppState>();
    let log_path = &state.log_path;

    #[cfg(windows)]
    {
        let path_str = log_path.to_string_lossy().to_string();
        std::process::Command::new("explorer")
            .arg(format!("/select,{path_str}"))
            .spawn()
            .map_err(|e| format!("Failed to open log file in explorer: {e}"))?;
    }

    #[cfg(not(windows))]
    {
        std::process::Command::new("xdg-open")
            .arg(log_path)
            .spawn()
            .map_err(|e| format!("Failed to open log file: {e}"))?;
    }

    Ok(())
}

fn windows_open_cmd_args(url: &str) -> [String; 2] {
    // `cmd /C start "" URL` re-parses `&` as a command separator unless the URL
    // is quoted as part of the /C script. OAuth authorize URLs always contain `&`.
    let safe = url.replace('"', "");
    ["/C".to_string(), format!("start \"\" \"{safe}\"")]
}

#[tauri::command]
fn open_external_url(url: String) -> Result<(), String> {
    if !url.starts_with("http://") && !url.starts_with("https://") {
        return Err("Only http and https URLs are allowed".to_string());
    }

    #[cfg(windows)]
    {
        std::process::Command::new("cmd")
            .args(windows_open_cmd_args(&url))
            .spawn()
            .map_err(|e| format!("Failed to open URL in browser: {e}"))?;
    }

    #[cfg(target_os = "macos")]
    {
        std::process::Command::new("open")
            .arg(&url)
            .spawn()
            .map_err(|e| format!("Failed to open URL in browser: {e}"))?;
    }

    #[cfg(all(not(windows), not(target_os = "macos")))]
    {
        std::process::Command::new("xdg-open")
            .arg(&url)
            .spawn()
            .map_err(|e| format!("Failed to open URL in browser: {e}"))?;
    }

    Ok(())
}

#[tauri::command]
fn retry_gateway(app: tauri::AppHandle) -> Result<(), String> {
    let state = app.state::<AppState>();

    // 1. Terminate old sidecar if present
    if let Ok(mut guard) = state.sidecar.lock() {
        if let Some(mut child) = guard.take() {
            let _ = child.kill();
            let _ = child.wait();
        }
    }

    let resource_dir = app.path().resource_dir().ok();
    let python = runtime::resolve_python(resource_dir.as_deref())?;
    let config_path = runtime::resolve_config_path();
    let log_path = state.log_path.clone();

    // 2. Spawn new sidecar
    let child = runtime::spawn_sidecar(&python, None, None, resource_dir.as_deref(), &log_path)?;
    if let Ok(mut guard) = state.sidecar.lock() {
        *guard = Some(child);
    }

    // 3. Spawn background wait thread
    let sidecar_for_wait = state.sidecar.clone();
    let log_path_for_wait = log_path.clone();
    let app_handle = app.clone();

    std::thread::spawn(move || {
        let timeout = Duration::from_secs(90);
        let win = app_handle.get_webview_window("main");
        match runtime::wait_ready(
            &config_path,
            &log_path_for_wait,
            &sidecar_for_wait,
            timeout,
        ) {
            Ok((host, port, secret)) => {
                if let Some(window) = win {
                    let target_url_str = runtime::bootstrap_url(&host, port, &secret);
                    if let Ok(target_url) = Url::parse(&target_url_str) {
                        let _ = window.navigate(target_url);
                    }
                }
            }
            Err(err) => {
                if let Some(window) = win {
                    let err_json = serde_json::to_string(&err).unwrap_or_default();
                    let log_json = serde_json::to_string(
                        &log_path_for_wait.to_string_lossy().to_string(),
                    )
                    .unwrap_or_default();
                    let _ =
                        window.eval(&format!("window.__showError({err_json}, {log_json});"));
                }
            }
        }
    });

    Ok(())
}

#[cfg(test)]
mod tests {
    use super::windows_open_cmd_args;

    #[test]
    fn windows_start_quotes_oauth_query_string() {
        let url = "https://claude.ai/oauth/authorize?code=true&response_type=code";
        let args = windows_open_cmd_args(url);
        assert_eq!(args[0], "/C");
        assert_eq!(
            args[1],
            r#"start "" "https://claude.ai/oauth/authorize?code=true&response_type=code""#
        );
    }
}

pub fn run() {
    let sidecar_state: Arc<Mutex<Option<Child>>> = Arc::new(Mutex::new(None));
    let sidecar_cleanup = sidecar_state.clone();

    let mut builder = tauri::Builder::default();

    builder = builder
        .invoke_handler(tauri::generate_handler![open_log_file, retry_gateway, open_external_url])
        .setup(move |app| {
            let app_handle = app.handle();
            let resource_dir = app_handle.path().resource_dir().ok();

            let app_data_dir = app_handle.path().app_data_dir().unwrap_or_else(|_| {
                let home = std::env::var("USERPROFILE")
                    .or_else(|_| std::env::var("HOME"))
                    .unwrap_or_else(|_| ".".to_string());
                PathBuf::from(home).join(".nanobot").join("desktop")
            });
            let log_path = app_data_dir.join("gateway-launch.log");

            // Manage application state
            app.manage(AppState {
                sidecar: sidecar_state.clone(),
                log_path: log_path.clone(),
            });

            // Create main splash window
            let window = WebviewWindowBuilder::new(
                app,
                "main",
                WebviewUrl::App("index.html".into()),
            )
            .title("NextTutorBot")
            .inner_size(1100.0, 760.0)
            .center()
            .initialization_script(r#"
              (function() {
                var _open = window.open;
                window.open = function(url, target, features) {
                  if (typeof url === 'string' && /^https?:\/\//i.test(url)) {
                    try {
                      var parsed = new URL(url, window.location.href);
                      if (parsed.hostname !== '127.0.0.1' && parsed.hostname !== 'localhost') {
                        if (window.__TAURI__ && window.__TAURI__.core) {
                          window.__TAURI__.core.invoke('open_external_url', { url: url }).catch(console.error);
                          return null;
                        }
                      }
                    } catch (e) {}
                  }
                  return _open ? _open.apply(window, arguments) : null;
                };
              })();
            "#)
            .build()?;

            // Resolve Python executable
            let python = match runtime::resolve_python(resource_dir.as_deref()) {
                Ok(p) => p,
                Err(err) => {
                    let err_json = serde_json::to_string(&err).unwrap_or_default();
                    let log_json = serde_json::to_string(&log_path.to_string_lossy().to_string())
                        .unwrap_or_default();
                    let _ = window.eval(&format!("window.__showError({err_json}, {log_json});"));
                    return Ok(());
                }
            };

            let config_path = runtime::resolve_config_path();

            // Spawn sidecar process
            match runtime::spawn_sidecar(
                &python,
                None,
                None,
                resource_dir.as_deref(),
                &log_path,
            ) {
                Ok(child) => {
                    if let Ok(mut guard) = sidecar_state.lock() {
                        *guard = Some(child);
                    }
                }
                Err(err) => {
                    let err_json = serde_json::to_string(&err).unwrap_or_default();
                    let log_json = serde_json::to_string(&log_path.to_string_lossy().to_string())
                        .unwrap_or_default();
                    let _ = window.eval(&format!("window.__showError({err_json}, {log_json});"));
                    return Ok(());
                }
            }

            // Background thread to poll until the gateway is ready
            let win_clone = window.clone();
            let sidecar_for_wait = sidecar_state.clone();
            let log_path_for_wait = log_path.clone();

            std::thread::spawn(move || {
                let timeout = Duration::from_secs(90);
                match runtime::wait_ready(
                    &config_path,
                    &log_path_for_wait,
                    &sidecar_for_wait,
                    timeout,
                ) {
                    Ok((host, port, secret)) => {
                        let target_url_str = runtime::bootstrap_url(&host, port, &secret);
                        match Url::parse(&target_url_str) {
                            Ok(target_url) => {
                                let _ = win_clone.navigate(target_url);
                            }
                            Err(e) => {
                                let err_msg =
                                    format!("Failed to parse gateway URL '{target_url_str}': {e}");
                                let err_json = serde_json::to_string(&err_msg).unwrap_or_default();
                                let log_json = serde_json::to_string(
                                    &log_path_for_wait.to_string_lossy().to_string(),
                                )
                                .unwrap_or_default();
                                let _ = win_clone.eval(&format!(
                                    "window.__showError({err_json}, {log_json});"
                                ));
                            }
                        }
                    }
                    Err(err) => {
                        let err_json = serde_json::to_string(&err).unwrap_or_default();
                        let log_json = serde_json::to_string(
                            &log_path_for_wait.to_string_lossy().to_string(),
                        )
                        .unwrap_or_default();
                        let _ =
                            win_clone.eval(&format!("window.__showError({err_json}, {log_json});"));
                    }
                }
            });

            Ok(())
        });

    let app = builder
        .build(tauri::generate_context!())
        .expect("error while building tauri application");

    app.run(move |app_handle, event| match event {
        RunEvent::ExitRequested { api, .. } => {
            if SHUTTING_DOWN.swap(true, Ordering::SeqCst) {
                // Our own `exit()` after cleanup: let the app close now.
                return;
            }
            // Hold the process open until the gateway is stopped (bounded by the watchdog).
            api.prevent_exit();

            let resource_dir = app_handle.path().resource_dir().ok();
            let handle = app_handle.clone();
            let sidecar = sidecar_cleanup.clone();

            std::thread::spawn(move || {
                if let Ok(python) = runtime::resolve_python(resource_dir.as_deref()) {
                    runtime::shutdown_gateway(&python, resource_dir.as_deref());
                }
                if let Ok(mut guard) = sidecar.lock() {
                    if let Some(mut child) = guard.take() {
                        let _ = child.kill();
                        let _ = child.wait();
                    }
                }
                handle.exit(0);
            });
        }
        // Final teardown is handled by the worker above.
        RunEvent::Exit => {}
        _ => {}
    });
}

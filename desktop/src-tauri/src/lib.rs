pub mod runtime;

use std::path::PathBuf;
use std::process::Child;
use std::sync::{Arc, Mutex};
use std::time::Duration;
use tauri::{Manager, RunEvent, Url, WebviewUrl, WebviewWindowBuilder};

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

pub fn run() {
    let sidecar_state: Arc<Mutex<Option<Child>>> = Arc::new(Mutex::new(None));
    let sidecar_cleanup = sidecar_state.clone();

    let mut builder = tauri::Builder::default();

    builder = builder
        .invoke_handler(tauri::generate_handler![open_log_file, retry_gateway])
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
            .title("Nanobot")
            .inner_size(1100.0, 760.0)
            .center()
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

    app.run(move |_app_handle, event| {
        if matches!(event, RunEvent::ExitRequested { .. } | RunEvent::Exit) {
            if let Ok(mut guard) = sidecar_cleanup.lock() {
                if let Some(mut child) = guard.take() {
                    let _ = child.kill();
                    let _ = child.wait();
                }
            }
        }
    });
}

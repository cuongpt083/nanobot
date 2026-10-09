# Nanobot Desktop (Tauri Shell)

Native desktop shell for nanobot built with [Tauri v2](https://v2.tauri.app/).

## Prerequisites

- [Bun](https://bun.sh/)
- [Rust toolchain](https://rustup.rs/) (Cargo)
- [uv](https://docs.astral.sh/uv/) / Python 3.11+
- Platform webview (Microsoft Edge WebView2 on Windows, WebKitGTK on Linux)

## Development Mode

In development, the Tauri shell runs against your local nanobot environment without needing to bundle the Python runtime or rebuild the Rust shell on Python/WebUI edits.

```powershell
# Windows PowerShell
cd desktop
$env:NANOBOT_DESKTOP_PYTHON = "$PWD\..\.venv\Scripts\python.exe"
bun install
bun run dev
```

```bash
# macOS / Linux
cd desktop
export NANOBOT_DESKTOP_PYTHON="$(pwd)/../.venv/bin/python"
bun install
bun run dev
```

In dev mode, modifying Python source files or the WebUI does not require rebuilding the Rust Tauri shell. Just restart the application to reload the gateway.

## Production Build

To build the standalone installer with the embedded relocatable Python runtime and pre-installed dependencies:

```bash
cd desktop
bun install
bun run build
```

This single command:
1. Downloads and caches `python-build-standalone` (`cpython-3.12.x-install_only`).
2. Builds the nanobot wheel (including the bundled WebUI).
3. Installs nanobot + dependencies (including `api` extra) into `desktop/runtime/site-packages/`.
4. Runs `tauri build` to package the executable, resources, and installer.

### Output Installers

The generated installers and bundles are located at:
- **Windows**: `desktop/src-tauri/target/release/bundle/nsis/` and `msi/`
- **macOS**: `desktop/src-tauri/target/release/bundle/dmg/` and `macos/`
- **Linux**: `desktop/src-tauri/target/release/bundle/deb/` and `appimage/`

## Environment Variables

| Variable | Description |
| --- | --- |
| `NANOBOT_DESKTOP_PYTHON` | Path to a custom Python interpreter (e.g. repo `.venv`). When set, dev mode is active and bundled runtime is bypassed. |
| `NANOBOT_BSK_PATH` | Path to the bundled `bsk` binary for the browser tools (Phase 10). Set by the desktop app to its own resources; when unset, `bsk` is looked up on PATH. |
| `NANOBOT_DESKTOP_CONFIG` | Optional custom path to `config.json` (defaults to `~/.nanobot/config.json`). |
| `NANOBOT_DESKTOP_WORKSPACE` | Optional workspace directory passed to the sidecar as `--workspace <dir>`. |
| `PYTHONPATH` | Automatically configured in production by the shell to point to the embedded `site-packages`. |

## Architecture & Lifecycle

- The Rust shell spawns `python -m nanobot webui --no-open --yes` in a non-interactive, non-TTY background process.
- The shell displays a native splash screen (`frontend/index.html`) and polls `GET /webui/bootstrap` on the local WebSocket HTTP channel.
- Once ready, the webview navigates to `http://127.0.0.1:<port>/#/?bootstrapSecret=<secret>`.
- When the desktop window is closed, the Rust shell terminates the sidecar process, which automatically releases the gateway client lease and shuts down the gateway cleanly.

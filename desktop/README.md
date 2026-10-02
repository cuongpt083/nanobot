# Nanobot Desktop (Tauri Shell)

Native desktop shell for nanobot built with [Tauri v2](https://v2.tauri.app/).

## Prerequisites

- [Bun](https://bun.sh/)
- [Rust toolchain](https://rustup.rs/) (Cargo)
- [uv](https://docs.astral.sh/uv/) / Python 3.11+
- Platform webview (WebView2 on Windows, WebKitGTK on Linux)

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

## Production Build

To build the standalone installer with bundled Python runtime:

```bash
cd desktop
bun install
bun run build
```

The resulting installers will be placed under `src-tauri/target/release/bundle/`.

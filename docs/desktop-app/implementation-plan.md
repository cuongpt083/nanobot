# Desktop App — Implementation Plan

This is the phased, agent-ready plan for packaging nanobot as a Tauri v2 desktop app.
Each task states a **goal**, a **how-to**, its **artifacts**, and a **Definition of Done (DoD)**.
For architecture background and source references, see
[engineering-notes.md](./engineering-notes.md).

**Read [README.md](./README.md) → "Agent conventions" before starting.**

> Scope note: this plan intentionally avoids modifying `nanobot/`, `webui/`, or `tui/` in
> Phases 1–3. Everything is additive under `desktop/`.

---

## Design summary

- **Tauri v2 "thin shell".** Rust spawns the Python sidecar
  `python -m nanobot webui --no-open --yes`, waits for the WebUI, then opens the webview at
  `http://127.0.0.1:<port>/#/?bootstrapSecret=<secret>`. Tauri does **not** bundle the frontend;
  the gateway serves the SPA.
- **Bundled Python runtime.** Embed **python-build-standalone** (relocatable) + `site-packages`
  installed with `pip install --target`, shipped as Tauri **resources**. No PyInstaller.
- **Everything lives in `desktop/`.**
- **Rebuild priority.** In dev, changing nanobot source must not require a Tauri rebuild.

---

## Conventions (apply to every task)

- Run dev: in `desktop/`, set `NANOBOT_DESKTOP_PYTHON` to the repo venv interpreter, then
  `bun run dev`. Windows example:
  `set NANOBOT_DESKTOP_PYTHON=%CD%\..\.venv\Scripts\python.exe && bun run dev`.
- Run build: in `desktop/`, `bun run build`.
- Sidecar command is always `python -m nanobot webui --no-open --yes`.
- Shared constants: WebUI `http://127.0.0.1:8765`; health `http://127.0.0.1:18790/health`;
  bootstrap route `/webui/bootstrap`.
- Config keys: `channels.websocket.{enabled,host,port,tokenIssueSecret,token}` (camelCase JSON).
- Update the [task checklist](#task-checklist) as tasks complete.

---

## Phase 0 — Preparation

### T0.1 — Confirm the toolchain

**Goal:** the machine can build a Tauri v2 app and produce a Python runtime bundle.

**How-to**
- Verify: `rustc --version`, `cargo --version`, `bun --version`, `node --version`,
  `python --version` (>= 3.11), `uv --version`.
- Windows: confirm the WebView2 runtime is present (default on Windows 11).
- Confirm `@tauri-apps/cli` v2 installs via bun and `tauri --version` reports `2.x`.

**Artifacts:** notes in the [session notes](#session-notes) section.

**DoD**
- [ ] All commands above run and versions are recorded.
- [ ] `tauri --version` reports v2.x.

**Verify:** re-run the commands; no errors.

---

## Phase 1 — Scaffold + dev shell (no Python bundling yet)

### T1.1 — Scaffold the Tauri v2 project under `desktop/`

**Goal:** a buildable Tauri v2 skeleton with a splash page.

**How-to**
- `desktop/package.json`: `devDependencies: { "@tauri-apps/cli": "^2" }`; scripts
  `"dev": "tauri dev"`, `"build": "tauri build"`, `"runtime": "python scripts/build_runtime.py"`.
- `desktop/frontend/index.html`: splash ("Starting Nanobot…") exposing
  `window.__showError(message, logPath)` for Rust to call on failure.
- `desktop/src-tauri/Cargo.toml`: `tauri = { version = "2" }`, `[build-dependencies] tauri-build = "2"`,
  plus `serde`, `serde_json`, `ureq` (blocking HTTP probe).
- `desktop/src-tauri/build.rs`: `tauri_build::build()`.
- `desktop/src-tauri/tauri.conf.json` (minimal):
  `productName: "Nanobot"`, `identifier: "ai.nanobot.desktop"`, `version: "0.1.0"`,
  `build.frontendDist: "../frontend"`, `app.windows: []` (window is created in code),
  `app.security.csp: null`, `bundle.active: true`.
- `desktop/src-tauri/capabilities/default.json`: minimal capability (e.g. `"core:default"`).
- `desktop/src-tauri/icons/`: placeholder icons (generate via `tauri icon`).
- `desktop/.gitignore`: `runtime/`, `src-tauri/target/`, `node_modules/`.

**Artifacts:** the files above.

**DoD**
- [ ] `cd desktop && bun install` succeeds and produces a lockfile.
- [ ] `cargo check` (in `desktop/src-tauri`) is clean (after T1.2/T1.3).
- [ ] `tauri.conf.json` validates against the Tauri v2 schema (no unknown/wrong fields).

**Verify:** `bun install`, then (after T1.3) `bun run dev` shows the splash window.

**Refs:** Tauri v2 config schema; `tauri icon` for icons.

---

### T1.2 — `runtime.rs`: resolve / spawn / wait

**Goal:** one Rust module that prepares and waits for the gateway.

**How-to**
- `resolve_python(app) -> Result<PathBuf, String>`
  - If `NANOBOT_DESKTOP_PYTHON` is set → use it (dev).
  - Else → `<resource_dir>/runtime/python/<bin>`
    (Windows `runtime/python/python.exe`; macOS/Linux `runtime/python/bin/python3`).
  - Return a clear error if missing.
- `resolve_config_path() -> PathBuf`
  - `NANOBOT_DESKTOP_CONFIG` if set; else `~/.nanobot/config.json` (matches nanobot's default).
- `read_webui_endpoint(config_path) -> Option<(String, u16, String)>`
  - Read JSON; take `channels.websocket.host` (default `127.0.0.1`), `port` (default `8765`),
    secret = `tokenIssueSecret` | `token` | `""`. Accept snake_case too.
- `spawn_sidecar(python, config_path, log_file) -> std::process::Child`
  - Args: `-m nanobot webui --no-open --yes` (+ `--config <path>` when a custom path is used;
    + `--workspace <dir>` when `NANOBOT_DESKTOP_WORKSPACE` is set).
  - Env: `PYTHONUNBUFFERED=1`; in production also
    `PYTHONPATH=<resource_dir>/runtime/site-packages`. Do not set `PYTHONHOME`.
  - Redirect stdout+stderr to `log_file` (`<app_data_dir>/gateway-launch.log`).
  - Windows: use `CREATE_NO_WINDOW`.
- `wait_ready(config_path, timeout = 90s) -> Result<(String, u16, String), String>`
  - Loop: (a) read config for the endpoint (config appears only after the first run);
    (b) `GET http://<host>:<port>/webui/bootstrap` with header `X-Nanobot-Auth: <secret>`
    when a secret exists; accept HTTP `200`.
  - On timeout, return an error including the log path for the UI.
- `bootstrap_url(host, port, secret) -> String`
  - `http://<host>:<port>/#/?bootstrapSecret=<urlencoded secret>`; without a secret, no `#/`.
  - Must match `_webui_browser_url` in `nanobot/cli/webui_support.py`.

**Artifacts:** `desktop/src-tauri/src/runtime.rs`.

**DoD**
- [ ] All public functions compile and handle errors (no `unwrap()` on real paths).
- [ ] Unit tests for `bootstrap_url` (secret with special chars) and `read_webui_endpoint`
      (sample JSON) pass with `cargo test`.
- [ ] Generated URL matches `_webui_browser_url`'s format.

**Verify:** `cargo test` in `desktop/src-tauri`.

**Refs:** `nanobot/cli/webui_support.py:320,341`; `nanobot/cli/tui_launcher.py`
(`_tui_gateway_connection`, `_ensure_gateway`); `nanobot/gateway/runtime.py:108,420`.

---

### T1.3 — `lib.rs`: window + lifecycle

**Goal:** start the sidecar, open the window, navigate, and clean up.

**How-to**
- `main.rs`: `fn main() { desktop_lib::run() }` with
  `#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]`.
- `lib.rs` `run()`:
  - `.setup(|app| { ... })`:
    1. resolve python + config path; spawn sidecar; store `Child` + log path in managed state.
    2. create the window: `WebviewWindowBuilder::new(app, "main", WebviewUrl::App("index.html".into()))`
       (~1100×760, centered) as the splash.
    3. background thread: `wait_ready(...)`:
       - OK → `window.navigate(Url::parse(&bootstrap_url)?)`.
       - ERR → `window.eval("window.__showError(...)")` with message + log path.
    4. watch the sidecar: if it exits early, surface the error on the splash.
  - `.build(...)?.run(|app, event| { if matches!(event, RunEvent::ExitRequested {..} | RunEvent::Exit) { kill sidecar } })`.
  - Killing the sidecar releases the lease → the on-demand gateway stops (no process-tree kill needed).

**Artifacts:** `desktop/src-tauri/src/main.rs`, `desktop/src-tauri/src/lib.rs`.

**DoD**
- [ ] App shows the splash then navigates to the WebUI when the gateway is ready.
- [ ] On sidecar failure/timeout, the splash shows the error + log path (no blank window).
- [ ] Exiting the app kills the sidecar (verify in Task Manager / `nanobot gateway status`).

**Verify:** see T1.4.

**Refs:** Tauri v2 `WebviewWindowBuilder`, `WebviewUrl::App/External`, `window.navigate`,
`RunEvent`. **Verify** loopback external navigation; if blocked, add minimal
`app.security` / capability config.

---

### T1.4 — Dev smoke test on Windows

**Goal:** prove the end-to-end flow works in dev mode (no bundling).

**How-to**
- Prepare the repo venv with nanobot editable (`uv pip install -e .`) and ensure the WebUI
  bundle is built (first `nanobot webui` builds it, or `cd webui && bun run build`).
- Run: `set NANOBOT_DESKTOP_PYTHON=<repo>\.venv\Scripts\python.exe && bun run dev`.

**DoD**
- [ ] Window opens, WebUI loads, one message is sent and a reply is received.
- [ ] Sidecar non-TTY check: running `python -m nanobot webui --no-open --yes` in a
      non-TTY shell does not hang on a prompt and still starts the gateway.
      (`_ensure_interactive_tty_mode()` returns early when not a TTY —
      `nanobot/cli/terminal.py`.)
- [ ] **Rebuild simplicity:** edit one nanobot Python line (e.g. a log message), restart the
      app → the change appears **without rebuilding Tauri**.
- [ ] Exiting the app makes `nanobot gateway status` report stopped (on-demand gateway).

**Verify:** observe the steps above.

**Refs:** `nanobot/cli/webui.py`; `docs/webui.md`.

---

## Phase 2 — Python runtime bundling

### T2.1 — `fetch_python_runtime.py`

**Goal:** download python-build-standalone for the current platform/arch into `desktop/runtime/python/`.

**How-to**
- Determine target `{win32|darwin|linux}-{x64|arm64}` from `platform.system()/machine()`.
- Download the relocatable "install_only" build from `astral-sh/python-build-standalone`
  (pin a version, e.g. 3.12.x); extract into `desktop/runtime/python/`.
- Cache the archive in `desktop/.cache/` to avoid re-downloading.
- Skip if the expected version is already present (idempotent).

**Artifacts:** `desktop/scripts/fetch_python_runtime.py`.

**DoD**
- [ ] Runs on Windows and produces `desktop/runtime/python/python.exe`.
- [ ] Running twice does not re-download (cache hit).

**Verify:** `python scripts/fetch_python_runtime.py` twice.

**Refs:** download + checksum precedent in `nanobot/cli/tui_launcher.py`.

---

### T2.2 — `build_python_runtime.py`

**Goal:** install nanobot + deps into `desktop/runtime/site-packages/`.

**How-to**
- Build the wheel from source: `uv build --wheel` (uses the existing hatchling + webui hook:
  `hatch_build.py`, `nanobot/webui/build.py`). The wheel includes `nanobot/web/dist`.
- `pip install --target desktop/runtime/site-packages <wheel>` (do **not** use a venv — venvs
  hardcode paths) + extras selected via arguments (core by default).
- Use `--upgrade` when reinstalling for cleanliness; consider `--no-compile` for speed.

**Artifacts:** `desktop/scripts/build_python_runtime.py`.

**DoD**
- [ ] `desktop/runtime/site-packages/nanobot/` exists with `web/dist/index.html`, `skills/`,
      `templates/`.
- [ ] `desktop/runtime/python/python.exe -c "import nanobot; print(nanobot.__version__)"`
      works with `PYTHONPATH=desktop/runtime/site-packages`.

**Verify:** run the import command; check the three package-data paths exist.

**Refs:** `pyproject.toml:25-162` (deps + extras); `hatch_build.py`; `nanobot/webui/build.py`.

---

### T2.3 — `build_runtime.py` + `package.json` scripts

**Goal:** one incremental command refreshes the runtime.

**How-to**
- `build_runtime.py`: call T2.1 → T2.2; skip reinstall if the wheel hash is unchanged.
- `desktop/package.json`: `"runtime": "python scripts/build_runtime.py"`,
  `"build": "python scripts/build_runtime.py && tauri build"`.

**Artifacts:** `desktop/scripts/build_runtime.py`, `desktop/package.json`.

**DoD**
- [ ] `bun run runtime` completes; the second run is fast (reinstall skipped).

**Verify:** run twice, compare logs/time.

---

### T2.4 — Production python resolution + package-data verification

**Goal:** the shell runs from the bundled runtime (no venv).

**How-to**
- Enable the production branch in `resolve_python` (T1.2): use `resources/runtime/python/...`.
- Set `PYTHONPATH=<resource_dir>/runtime/site-packages` when spawning.
- Locally, simulate by copying `desktop/runtime/` into a resources dir and checking that
  `nanobot.web.__file__` resolves to the bundled `dist`.

**DoD**
- [ ] In production mode (no `NANOBOT_DESKTOP_PYTHON`), the app starts the gateway from the
      bundled runtime.
- [ ] The WebUI loads (proving package-data resolves).

**Verify:** run the app without the dev env var; `GET /webui/bootstrap` returns 200.

**Refs:** `nanobot/webui/build.py:78`; `nanobot/channels/manager.py:49`.

---

## Phase 3 — Bundle & installer

### T3.1 — Bundle config in `tauri.conf.json`

**How-to**
- `bundle.resources: { "../../runtime": "runtime/" }`.
- `bundle.icon`: real icons.
- `bundle.targets`: platform defaults (`msi`/`nsis`, `dmg`/`app`, `deb`/`appimage`).
- macOS: add `bundle.macOS.{signingIdentity,entitlements}` (see T3.3).

**DoD**
- [ ] After `bun run build`, `runtime/` is present in the bundle's resources.

**Verify:** unpack the MSI/DMG and inspect.

---

### T3.2 — One-command build + docs

**Goal:** `bun run build` is all that is needed after changing nanobot source.

**How-to:** ensure `desktop/README.md` documents dev vs build, env vars, and artifact locations.

**DoD**
- [ ] `cd desktop && bun run build` produces installers in `src-tauri/target/release/bundle/`.
- [ ] `desktop/README.md` is sufficient for a newcomer to build and run.

**Verify:** clean build from a fresh branch.

---

### T3.3 — macOS: sign & notarize the embedded Python *(only when building on macOS)*

**Goal:** the macOS app opens on other machines.

**How-to**
- Sign all binaries/dylibs under `runtime/python/` and `site-packages/` (recursive `codesign`
  after `tauri build`, before notarizing); add entitlements if required
  (`com.apple.security.cs.allow-jit`, `allow-unsigned-executable-memory`).

**DoD**
- [ ] `codesign --verify --deep --strict` passes; `spctl --assess` passes; notarization succeeds.

**Verify:** install on a clean macOS machine (no Python).

**Refs:** Tauri v2 macOS signing docs. **Highest-risk step.**

---

### T3.4 — Windows: installer test

**Goal:** the MSI/NSIS installer works on a clean machine.

**DoD**
- [ ] Installs on a machine without Python → app runs, WebUI chat works.
- [ ] Uninstall is clean; note SmartScreen behavior.

**Verify:** clean Windows machine / VM.

---

## Phase 4 — Robustness & UX

### T4.1 — Port conflicts + error screen + retry/open-log

**Goal:** common failures are reported clearly with an action.

**How-to**
- `wait_ready` distinguishes: timeout, sidecar exited early, port occupied (TCP open but
  bootstrap ≠ 200).
- Splash shows: message + `gateway-launch.log` path + "Retry" and "Open log" actions
  (`tauri-plugin-opener` or explorer).

**DoD**
- [ ] Simulated port conflict → clear message + hint to run `nanobot gateway status/stop`.
- [ ] Retry restarts the sidecar without reopening the app.

**Verify:** pre-start `nanobot gateway --background`, then open the app.

---

### T4.2 — Verify lifecycle semantics (attach vs managed)

**Goal:** never disrupt the user's gateway.

**How-to:** confirm that a user-started persistent gateway
(`nanobot gateway --background`) is **not** stopped when the app exits, while an on-demand
gateway created by the app **is**.

**DoD**
- [ ] Both scenarios verified and recorded.

**Refs:** `nanobot/gateway/runtime.py:420,683` (`GatewayClientLease`, `monitor_gateway_clients`).

---

### T4.3 (Optional) — Native surface via the `nanobotHost` bridge

**Goal:** unlock "native" capabilities (`runtime_surface == "native"`).

**How-to:** use `window.nanobotHost` / `nanobot-host://`
(already present in `webui/src/lib/runtime.ts`) so the shell proxies the engine instead of
loading the SPA as a plain browser page.

**DoD:** (only if prioritized) bootstrap returns `runtime_surface: "native"`.

**Refs:** `webui/src/lib/runtime.ts`; `nanobot/webui/ws_http.py:436,710`.

---

## Task checklist

- [x] T0.1 Confirm toolchain
- [x] T1.1 Scaffold `desktop/`
- [x] T1.2 `runtime.rs`
- [x] T1.3 `lib.rs`
- [x] T1.4 Dev smoke test (Windows)
- [x] T2.1 `fetch_python_runtime.py`
- [x] T2.2 `build_python_runtime.py`
- [x] T2.3 `build_runtime.py` + scripts
- [x] T2.4 Production resolution + package-data
- [x] T3.1 Bundle config
- [x] T3.2 One-command build + docs
- [ ] T3.3 macOS signing (when building on macOS)
- [x] T3.4 Windows installer test
- [ ] T4.1 Port-conflict + error UI
- [ ] T4.2 Lifecycle semantics
- [ ] T4.3 (Optional) Native surface

## Session notes

Append a dated line per work session: who/what, result, blockers.

- 2026-10-02: Completed Phase 0 (toolchain verified) and Phase 1 (scaffolded `desktop/`, implemented `runtime.rs` and `lib.rs`, verified unit tests and end-to-end dev smoke test on Windows). Gateway auto-start, bootstrap response, and cleanup on exit verified. No blockers.
- 2026-10-02: Completed Phase 2 (Python runtime bundling). Created `fetch_python_runtime.py` (downloading python-build-standalone with caching), `build_python_runtime.py` (uv wheel build + pip install into site-packages + sitecustomize.py for .pth handling), `build_runtime.py` orchestrator with `bun run runtime`. Verified production resolution and gateway bootstrap in standalone mode without `NANOBOT_DESKTOP_PYTHON`. All tests passing. No blockers.
- 2026-10-02: Completed Phase 3 (Bundle & Installer). Configured `bundle.resources` (`../runtime` mapping) and `bundle.targets: "all"` in `tauri.conf.json`. Updated `desktop/README.md` with full documentation of build commands, env vars, and artifact locations. Executed `bun run build` which built the release binary and successfully generated both NSIS (`Nanobot_0.1.0_x64-setup.exe`, 64.39 MB) and MSI (`Nanobot_0.1.0_x64_en-US.msi`, 106.17 MB) installers containing the entire standalone Python runtime and packages. No blockers.

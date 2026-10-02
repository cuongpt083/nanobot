# Desktop App (Tauri)

**Status: design / planning. No implementation code exists yet.**

This section documents the plan to package nanobot as a native desktop app with
[Tauri v2](https://v2.tauri.app/). It is written so that a contributor (human or AI agent)
can pick up the work with the minimum amount of additional research.

- [Implementation plan](./implementation-plan.md) — phased tasks with Definition of Done.
- [Engineering notes](./engineering-notes.md) — architecture findings, coupling points, risks,
  and exact source references.

## Goal

Ship a desktop app for nanobot **while keeping rebuilds cheap**: changing nanobot source
(Python or WebUI) should ideally not require rebuilding the Tauri shell.

## Key decisions

| Decision | Choice | Why |
| --- | --- | --- |
| Shell | Tauri v2 "thin shell" | Small, cross-platform, uses the OS webview |
| UI delivery | Webview points at the WebUI served by the gateway | The existing SPA is origin-agnostic; no frontend changes needed |
| Python runtime | Bundle **python-build-standalone** + `site-packages` as Tauri resources | Avoids every PyInstaller problem (dynamic discovery, entry points, `__file__` assets) |
| Gateway lifecycle | Spawn the sidecar `python -m nanobot webui --no-open --yes` | Reuses the existing setup + client-lease logic; keeps the Rust shell thin |
| Layout | Everything under `desktop/` | Monorepo; easy to reuse the repo venv and tooling |

## Architecture

```
┌──────────────────────── Tauri App (desktop/) ────────────────────────┐
│ Rust shell (src-tauri/src)                                            │
│  1. resolve python: NANOBOT_DESKTOP_PYTHON (dev) | resources/runtime  │
│  2. spawn: <python> -m nanobot webui --no-open --yes [--config ...]   │
│  3. poll config.json + GET /webui/bootstrap until 200                 │
│  4. window.navigate("http://127.0.0.1:<port>/#/?bootstrapSecret=...") │
│  5. on app exit → kill sidecar (lease released → gateway stops)       │
└──────────────────────────────┬───────────────────────────────────────┘
                               │ spawn (child process)
┌──────────────────────────────▼───────────────────────────────────────┐
│ Sidecar: python -m nanobot webui --no-open --yes                      │
│  • ensures ~/.nanobot/config.json + channels.websocket                │
│    (enabled, host=127.0.0.1, port=8765, tokenIssueSecret)            │
│  • ensures the webui bundle (nanobot/web/dist) is present             │
│  • ensure_on_demand_gateway + holds a GatewayClientLease              │
│  • follows logs (blocks) → lives as long as the app                   │
└──────────────────────────────┬───────────────────────────────────────┘
                               │ HTTP + WS on 127.0.0.1:8765
┌──────────────────────────────▼───────────────────────────────────────┐
│ Gateway + WebUI SPA (already exists — unchanged)                     │
└──────────────────────────────────────────────────────────────────────┘
```

## Target repository layout

```
desktop/
  package.json                 # bun scripts: dev / build / runtime
  README.md                    # short dev & build quickstart
  frontend/index.html          # splash + minimal error screen (Tauri placeholder)
  src-tauri/
    Cargo.toml
    build.rs
    tauri.conf.json
    capabilities/default.json
    icons/                     # app icons (placeholder, replace later)
    src/
      main.rs                  # entry → lib::run()
      lib.rs                   # setup, window, lifecycle
      runtime.rs               # resolve python, read config, spawn, wait_ready, url
  scripts/
    fetch_python_runtime.py    # download python-build-standalone → runtime/python/
    build_python_runtime.py    # build nanobot wheel + pip install --target
    build_runtime.py           # orchestrator: fetch → build → install
  runtime/                     # GENERATED, gitignored: python/ + site-packages/
  .gitignore                   # runtime/, src-tauri/target/, node_modules/
```

## Quickstart

> These commands describe the target once Phase 1 exists; they are the intended workflow.

### Development

```powershell
# From the repo root: install nanobot editable into the repo venv
uv pip install -e .

# In desktop/: point the shell at the repo venv (no Python bundling needed)
cd desktop
$env:NANOBOT_DESKTOP_PYTHON = "$PWD\..\.venv\Scripts\python.exe"   # Windows
bun install
bun run dev
```

In dev, **changing nanobot Python/WebUI source does not rebuild Tauri** — restart the app to
reload the gateway. Only Rust shell changes require a Tauri rebuild.

### Production build (one command)

```bash
cd desktop
bun run build        # build_runtime.py (fetch + build wheel + install) then tauri build
```

Output installers land in `desktop/src-tauri/target/release/bundle/`.

## Environment variables

| Variable | Purpose |
| --- | --- |
| `NANOBOT_DESKTOP_PYTHON` | Dev override: absolute path to a Python interpreter (e.g. the repo venv) |
| `NANOBOT_DESKTOP_CONFIG` | Optional custom config path (defaults to `~/.nanobot/config.json`) |
| `NANOBOT_DESKTOP_WORKSPACE` | Optional workspace passed to the sidecar as `--workspace` |
| `PYTHONPATH` | Set by the shell in production to `<resources>/runtime/site-packages` |

## Agent conventions

Read this before starting any task in the implementation plan:

- **Do not modify `nanobot/`, `webui/`, or `tui/`** for Phases 1–3. Add code only under
  `desktop/` plus these docs. If a change to core is genuinely required, open a separate task
  and justify it.
- **Always launch the sidecar as** `python -m nanobot webui --no-open --yes`. Do not call
  `nanobot gateway` directly in Phase 1 — the `webui` command already performs setup and
  holds the client lease.
- **Shared constants:** WebUI `http://127.0.0.1:8765`; health `http://127.0.0.1:18790/health`;
  bootstrap route `/webui/bootstrap`.
- **Relevant config keys:** `channels.websocket.{enabled,host,port,tokenIssueSecret,token}`
  (JSON uses camelCase).
- **Prefer reading `config.json`** over parsing sidecar stdout.
- Keep the [task checklist](./implementation-plan.md#task-checklist) and the session notes
  section up to date as you work.

## Risks (summary)

- Bundled app cannot `pip install` channel/optional extras at runtime → pre-bundle what you need.
- macOS code signing / notarization of the embedded Python is the fiddliest part.
- Fixed WebUI port (8765); port `0` is not supported by the launcher flow.
- Bundle size ~150–250 MB.

See [engineering-notes.md](./engineering-notes.md) for the full list and mitigations.

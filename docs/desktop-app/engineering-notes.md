# Desktop App — Engineering Notes

Background research that informs the [implementation plan](./implementation-plan.md).
Read this if you need to understand *why* the plan is shaped the way it is, or need exact
source references.

## Feasibility

Feasible, medium complexity. The blocker is **not** Tauri — it is carrying a Python runtime.
Using **python-build-standalone + `site-packages`** sidesteps every PyInstaller problem
(dynamic discovery, entry points, `__file__`-relative assets, runtime `pip install`).

## Architecture coupling (why the webview can just point at the gateway)

- **WebUI port** comes from `channels.websocket.port` (default `8765`;
  `nanobot/channels/websocket/runtime.py`), **not** `gateway.port` (default `18790`, health only;
  `nanobot/config/schema.py:414`).
- **Two independent listeners:** health `127.0.0.1:18790` (`/health`) and WebUI
  `127.0.0.1:8765`.
- **The SPA is origin-agnostic:** it uses relative `/api` and `/webui/bootstrap`, and derives the
  WebSocket URL from `window.location` (`webui/src/lib/bootstrap.ts`). No frontend changes needed
  when the webview loads the gateway's own origin.
- **Bootstrap auth:** if a secret is configured (`tokenIssueSecret`/`token`), the request must
  send `Authorization: Bearer <secret>` or `X-Nanobot-Auth: <secret>` (else 401). With no secret
  and a localhost request, it succeeds (`nanobot/webui/ws_http.py`).
- **Convenience URL:** `_webui_browser_url` produces
  `http://host:port/#/?bootstrapSecret=<secret>` (`nanobot/cli/webui_support.py:320`).
- **Channel + secret setup:** `_ensure_local_webui_channel` enables the channel, forces
  `host=127.0.0.1`, and generates `tokenIssueSecret`; it only applies with `--yes`/confirmation
  (`nanobot/cli/webui_support.py:341`).
- **Gateway lifetime:** `GatewayClientLease` + `monitor_gateway_clients` stop an on-demand gateway
  when the last client leaves; a persistent gateway (`--background`) is not stopped
  (`nanobot/gateway/runtime.py:420,683`).
- **`nanobot webui --no-open --yes`** is the ideal "sidecar client": it performs setup, ensures
  the gateway, holds a lease, and follows logs (blocking). Killing it releases the lease.
- **Non-TTY is safe:** `_ensure_interactive_tty_mode()` returns early when stdin is not a TTY
  (`nanobot/cli/terminal.py`).
- **`python -m nanobot`** works (`nanobot/__main__.py`).
- **Package data in the wheel:** `nanobot/web/dist/**`, `nanobot/skills/**`,
  `nanobot/templates/**` (`pyproject.toml:129-162`, `hatch_build.py`).

## Risks & mitigations

| Risk | Level | Mitigation |
| --- | --- | --- |
| Runtime `pip install` of channel/optional extras fails in a bundled app | High | Pre-bundle needed extras; document the limitation; never rely on runtime install |
| macOS signing/notarizing the embedded Python (many dylibs) | High | Recursive `codesign` + entitlements; dedicated task (T3.3) |
| Fixed WebUI port (8765) conflicts | Medium | Fixed port + clear error/retry UI (T4.1); port `0` unsupported |
| Large bundle (~150–250 MB) | Medium | Accepted; can prune unused deps |
| Windows SmartScreen/AV | Medium | Code signing if available; user guidance |
| `nanobot webui` behavior changes upstream | Medium | Pin expectations in T1.4; read `config.json` rather than parse stdout |
| Webview blocks loopback external navigation | Low | Verify in T1.3; minimal `app.security`/capability config if needed |
| `runtime_surface` = "web" (some native-only capabilities off) | Low | Out of v1 scope; T4.3 unlocks it later |

## Source references (do not modify)

- `nanobot/cli/webui.py` — the `webui` command (flags, flow, `--no-open`, `--yes`).
- `nanobot/cli/webui_support.py:320,341` — browser URL + channel/secret setup.
- `nanobot/cli/tui_launcher.py` — precedent for ensuring the gateway, reading config, and
  download/verify of a native binary.
- `nanobot/gateway/runtime.py:108,420,683` — child command, client lease, client monitor.
- `nanobot/cli/gateway.py` — `gateway` command flags.
- `nanobot/config/schema.py:414`; `nanobot/channels/websocket/runtime.py` — port config.
- `nanobot/webui/ws_http.py` — bootstrap auth + static serving.
- `nanobot/webui/build.py:78`; `hatch_build.py` — WebUI build/packaging.
- `nanobot/__main__.py`; `nanobot/cli/terminal.py`.
- `pyproject.toml:25-162` — deps, extras, packaging.
- `webui/src/lib/bootstrap.ts`, `webui/src/lib/runtime.ts` — SPA bootstrap/WS + `nanobotHost` hook.

## Decision notes

- **Bundle python-build-standalone instead of PyInstaller**, because nanobot relies on
  `pkgutil` scanning, entry points, and `__file__`-relative package data that are painful to freeze.
- **Webview points at the gateway URL instead of Tauri serving the SPA**, to avoid Vite `base`
  changes, CORS, and a bootstrap proxy.
- **Sidecar is `nanobot webui --no-open --yes`**, to reuse the existing setup + lease logic and
  keep the Rust shell thin.

# Spike 2.0: Pi 1.x Extension API Verification Results

**Date**: 2026-10-05  
**Pi Version**: 1.0.2 (`C:\Users\Admin\.pi\agent\install\releases\1.0.2\node_modules\@earendil-works\pi-coding-agent`)  
**Environment**: Windows AMD64, Node.js v24.20.0

---

## Assumptions & Verification Matrix

| Assumption | Expected Behavior | Spike Result | Status | Notes |
|---|---|---|---|---|
| **H1** | `--no-extensions` does not disable extensions loaded via `--extension` | Pass | **CONFIRMED** | `get_commands` includes commands registered by `--extension <path>` even when `--no-extensions` is specified. Auto-discovered user extensions (like `@dmpunk/pi-agy`) are successfully suppressed. |
| **H2** | `agent_before_settle` appends entries and returns `continue: true` in RPC mode | Pass | **CONFIRMED** | Verified using offline mock model via `pi.registerProvider("mock-provider", ...)`. Returned `{ continue: true, entries: [...] }` triggered continuation turns up to the guard limit, producing exactly 3 turns and settlement with 2 recorded continuation entries. |
| **H3** | Entries appended via `pi.appendEntry` appear in `get_entries` | Pass | **CONFIRMED** | Custom entries appended during lifecycle events (`session_start`, `agent_before_settle`, `report_result`) are retrievable via RPC `get_entries` with data intact. |
| **H4** | Extension commands can invoke `pi.setActiveTools` via `/nanobot-mode` in RPC mode | Pass | **CONFIRMED** | Sending `{"type": "prompt", "message": "/nanobot-mode plan"}` yielded `disposition: "handled"` and triggered `ctx.ui.notify("Nanobot mode set to: plan")`, adjusting active tools as configured. |

---

## Architectural Conclusions for Phase 2

1. **No Fallback Needed for H2**: Both in-extension acceptance gate execution (`agent_before_settle`) and tool restriction switching (`/nanobot-mode`) work natively as designed in the implementation plan.
2. **Deterministic CI / E2E Testing**: `pi.registerProvider` enables deterministic, 100% offline testing of Pi RPC protocol and extension interactions without live API key requirements or model costs.
3. **RPC Boundary Types**: In Pi 1.0.2, `agent_before_settle` returns `BoundaryResult { entries?: SessionBoundaryDraft[], continue?: boolean }` where drafts must use recognized draft shapes (`custom_message`, `custom`, `context_edit`, `compaction`).

---

## Bước 0 (wiring v2): shape `get_entries` / `appendEntry`

Xác minh trực tiếp từ type definitions đã cài (`@earendil-works/pi-coding-agent@1.0.2`, `dist/modes/rpc/rpc-types.d.ts`, `dist/core/session-manager.d.ts`, `dist/core/extensions/types.d.ts`) — không cần chạy live.

- **`pi.appendEntry(customType: string, data?: unknown)`** (`core/extensions/types.d.ts:1235`) → entry lưu trong session.
- **`CustomEntry`** = `SessionEntryBase & { type: "custom"; customType: string; data?: T }` (`core/session-manager.d.ts:83`). `SessionEntryBase` mang `id`, `parentId`, `timestamp`.
  ⇒ Entry của `report_result` là `{ id, parentId, timestamp, type: "custom", customType: "nanobot_report", data: <params> }`.
- **Lệnh `get_entries`**: request `{ id?, type: "get_entries", since?: string }` — **`since` là string (entry id), KHÔNG phải index int**. Response `{ type:"response", command:"get_entries", success:true, data: { entries: SessionEntry[], leafId: string | null } }`.
- **`entry_cursor` trong `CodingTask` phải là `str | None`** (lưu `leafId`), không phải int.
- Các lệnh/param liên quan đã xác nhận tồn tại trong RPC:
  - `set_model`: `{ provider: string, modelId: string }` → response `data: Model`.
  - `set_thinking_level`: `{ level: ThinkingLevel }` → success (không data).
  - `get_available_models`: `{}` → `data: { models: Model[] }`.
  - `get_available_thinking_levels`: `{}` → `data: { levels: ThinkingLevel[] }`.
  - `export_html`: `{ outputPath?: string }` → `data: { path: string }`.
  - `get_state`, `get_commands`, `get_session_stats`, `get_last_assistant_text`, `steer`, `follow_up`, `prompt`, `abort`.

Kết luận: parser `pi/entries.py` lọc `entry["type"] == "custom"` theo `entry["customType"]` và đọc `entry["data"]`; `PiClient.get_entries(since=leafId)` lưu `leafId` làm cursor kế tiếp.

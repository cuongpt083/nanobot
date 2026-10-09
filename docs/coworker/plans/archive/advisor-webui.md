> **Đã lưu trữ 2026-10-09.** Đã triển khai (Phase 1–3); các chỗ khác với thiết kế nằm ở cuối file.

# Implementation plan — Advisor-assisted coding + WebUI participants & config

Status: **implemented (Phases 1–3), with the deviations listed at the end**. Written 2026-09-30. Implements `docs/coworker/proposals/dual-brain-coding-agent.md` (Draft v2).
Branch: current (`develop`). Style: `feat(coworker): …`.

## Constraints

- Merge safety (`docs/coworker/README.md`): put new logic in `nanobot/coworker/` and new modules; keep edits to upstream files
  (`ws_http.py`, `settings_routes.py`, WebUI shell files) to small, additive wiring.
- Python 3.11, asyncio, ruff (E,F,I,N,W, 100 cols), basedpyright strict for `nanobot/coworker`.
- Advisor semantics do not change (executor decides; advisor only reviews; no forced pre/post-flight).
- No model / provider / effort / API-key fields for Pi or agy in any UI.

## Phase 1 — Backend

| Step | File(s) | Change |
|------|---------|--------|
| 1.1 | `coding/tools.py`, `coding/workspace.py` | `coding_agent(action="diff", id)`: read-only, returns the worktree diff capped at `DIFF_MAX_CHARS` (20 000) with a truncation note; error when the worktree is gone. Add `"diff"` to the action enum and description. |
| 1.2 | `hook.py` | `_maybe_nudge_advisor`: also run for injected turns of kind `coding_result` / `room_review`. For these kinds the "genuine user text" requirement is dropped and the trigger is "advisor enabled, budget left, breaker closed, advisor not called this run". Other injected kinds (including `advisor_review`) still never nudge. The text differs: coding → "review the diff (`coding_agent diff`)". |
| 1.3 | `directives.py` | `CODING` directive: consult advisor before delegating (after orient), after a second acceptance failure, and before recommending merge; read the diff with `coding_agent(action="diff")` first. |
| 1.4 | `advisor/consult.py`, `advisor/state.py` | In-flight registry `active_consults()` (session key → started_at, focus, model) maintained by `run_consult` (needs an optional `session_key` argument); `record_consult(session, …)` stores `last_consult {at, focus, duration_ms, ok, model}` in the session slot. `tool.py` passes the key and records the outcome. |
| 1.5 | `room/scheduler.py` | `_Room.active: dict[str, ActiveGuest]` (agent id → task, started_at, waiting) set/cleared in `_run_room`; `room_snapshot(session_key)` returns active, queued (pending + local queue mirrored on the room), waiting, recently finished (last 5). |
| 1.6 | `coding/tasks.py`, `coding/runner.py` | `CodingTask.live: dict` (`tool_count`, `last_tool`, `elapsed_s`, `updated_at`) updated in-memory per event (not persisted to disk per event; persisted with the normal `save`). Add `live` to `to_dict` but tolerate old files. |
| 1.7 | `status.py` | Fix coding task filter to `t.session_key == key` (plus running tasks of this session first). Add `participants[]` (coordinator, advisor, teammates, coding) and `advisor.last_consult`. Keep every existing key (backward compatible). |
| 1.8 | Tests | `tests/coworker/coding/test_diff_action.py`, additions to `test_hook.py`, `test_advisor.py`, `test_room.py`, `test_status.py`. |

Coordinator state comes from a per-session "turn running" set maintained by `CoworkerHook.before_run`/`on_finally`
(module-level `runtime.running_turns`).

## Phase 2 — WebUI participants

| Step | File(s) | Change |
|------|---------|--------|
| 2.1 | `webui/src/lib/types.ts`, `api.ts` | `CoworkerParticipant`, `CoworkerLastConsult`; `participants` and `advisor.last_consult` (optional for old servers). |
| 2.2 | `hooks/useCoworkerStatus.ts` | Adaptive polling: existing open-popover mode unchanged; new `active` option keeps polling every 3 s while any participant is not `idle`, and one refresh when idle; expose `refresh()`. |
| 2.3 | `components/coworker/CoworkerParticipantsStrip.tsx` | Header chips (icon + label + pulsing dot when `working`), hidden when everything is idle and no room armed. Click → opens inspector. |
| 2.4 | `CoworkerInspectorPopover.tsx` | Controlled `open` (so the strip can open it); Room and Coding sections become participant lists with state, elapsed, last tool; advisor shows last consult. |
| 2.5 | `ThreadShell.tsx` / `ThreadHeader.tsx` | Render the strip next to the inspector trigger (additive prop). |
| 2.6 | `CoworkerMessageCard.tsx` | Advisor card: parse real advice (`ADVISOR (model) — advice n/max:`) if present, nudge shown as small system line; coding card: diffstat as +/− numbers and backend badge. |
| 2.7 | i18n, tests | `en`/`vi` keys; vitest for strip, participants list, card parsing. |

## Phase 3 — Coworker settings

| Step | File(s) | Change |
|------|---------|--------|
| 3.1 | `nanobot/coworker/settings_api.py` (new) | `coworker_settings_payload()` → `{config, detection, presets, repos}`; `update_coworker_settings(values)` → validates with `CoworkerConfig`, atomic write of `coworker.json` (temp + `os.replace`), preserves unknown keys, returns the new payload; per-field errors as `WebUISettingsError`. Binary detection: `shutil.which` + `--version` with 3 s timeout, only for configured commands. |
| 3.2 | `nanobot/webui/settings_routes.py`, `ws_http.py` | Additive wiring: `GET /api/settings/coworker`, mutation `POST /api/settings/coworker/update` + WS mutation key `settings.coworker.update`. |
| 3.3 | `webui/src/lib/api.ts`, `types.ts` | `fetchCoworkerSettings`, `updateCoworkerSettings`. |
| 3.4 | `components/settings/capabilities/CoworkerSettings.tsx` + sub-forms | Tabs Advisor / Team / Coding; dirty tracking; save; field errors; danger confirm for `allow_unsandboxed`. |
| 3.5 | Settings navigation, `AppsSettings.tsx` | Register the Coworker page under Capabilities; add `Coding` filter with read-only Pi/agy cards linking to the Coding tab. |
| 3.6 | Tests | pytest for settings_api (validation, atomic write, unknown-key preservation, denylist), vitest for the form. |

## Verification

`ruff check nanobot/`, `uv run --no-sync basedpyright` (coworker), `pytest tests/coworker -q`, `cd webui && bun run test && bun run build`.

## Implementation notes and deviations

Done: 1.1–1.8, 2.1–2.5, 2.7, 3.1–3.6 (see the test files named below).

Deviations from the proposal / plan:

1. **Nudge kinds** — only `coding_result` gets the post-result advisor nudge (not `room_review`): a room review
   already ends in a coordinator report and an extra advisor turn on every room run would be noisy.
2. **Shared task registry (bug found and fixed)** — every `CodingRunner(...)` used to build a fresh `TaskRegistry`,
   and constructing one runs restart recovery, which marked *running* tasks `interrupted` on disk. Any
   `coding_agent` call, `/code` command or status poll therefore clobbered a live task, and `steer`/`abort` could not
   find the running backend (`_active_backends` was per instance). Registry and active backends are now
   process-wide (`shared_registry`, `_ACTIVE_BACKENDS`); direct `TaskRegistry(...)` construction still recovers.
   Tests: `tests/coworker/coding/test_shared_registry.py`.
3. **Config UI placement** — a "Coworker" row in Settings → Capabilities that opens a dialog (Advisor / Team / Coding
   tabs), reachable at `#/settings?section=coworker`; not a new sidebar section. `#/apps` gets a read-only `Coding` filter with
   Pi/agy cards that links to it.
4. **API shape** — `POST /api/settings/coworker/update` takes the sections (`advisor`, `room`, `coding`) as top-level
   payload keys; a submitted section replaces that section. Pass-through env names that look like credentials are
   rejected server-side.
5. **Advisor consult card (completed in M6 T6.1)**: rendered via `AdvisorConsultRow.tsx` and `advisor-consult-model.ts`
   in `AgentActivityCluster.tsx` (running state, collapsible markdown advice card, status chips).
   Deferred remaining: teammate message attribution metadata; Merge/Discard buttons on the coding card;
   per-session advisor dropdown; translations of the new keys beyond `en`/`vi` (the locale-shape test
   in `src/tests/i18n.test.tsx` already failed for the other locales because they lack every `coworker.*` key).
6. **Pre-existing failures observed** (unchanged by this work): `test_fake_pi_run_and_auto_cancel_ui`,
   `test_env_and_argv_hygiene`, `test_workspace_lifecycle_and_uncommitted_changes`,
   `test_distill_writes_a_valid_linear_draft`, `tests/webui/test_file_preview.py` symlink cases (Windows symlink
   privilege / encoding / POSIX-only `os.getpgid`).

Tests added: `tests/coworker/coding/test_diff_action.py`, `test_shared_registry.py`, additions to
`tests/coworker/test_hook.py`, `test_advisor.py`, `test_room.py`, `test_status.py`, new `test_settings_api.py`,
`tests/webui/test_settings_routes.py`; WebUI `src/tests/coworker-participants.test.tsx`, `coworker-settings.test.tsx`.

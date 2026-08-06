# Pilot Consolidated Implementation Plan

> **For agentic workers:** This plan supersedes `2026-07-30-product-first-pilot-implementation-plan.md` and `2026-07-31-pilot-completion-implementation-plan.md`. Those documents are archived at `docs/superpowers/archive/2026-07-31-pilot-remediation/` for traceability. The approved design specs (`2026-07-30-product-first-pilot-design.md` and `2026-07-31-pilot-completion-remediation-design.md`) remain authoritative.

**Goal:** Deliver an invite-only WebUI and Telegram pilot with private reasoning, reliable provider execution, consent-gated capture, user controls, and operational tooling. Then extend the platform to capture reasoning traces, curate them into fine-tuning data, and deploy a teacher-student architecture where a Small Language Model (Qwen3-4B-Instruct-2507 Q5_K_M) handles simple tasks and plans complex tasks under review by a Large Language Model teacher (DeepSeek V4 Flash).

**Architecture:** Preserve `AgentLoop`, `AgentRunner`, session JSONL, and existing channel/provider contracts as the chat path. Add narrow pilot services for routing/circuit, capture/privacy/store, feedback/retention, and health. Then add a distillation pipeline and SLM inference service for the teacher-student architecture.

**Tech Stack:** Python 3.11+, asyncio, Pydantic, stdlib sqlite3, pytest/pytest-asyncio, Ruff, basedpyright, React 18, TypeScript, Vite, Vitest, Telegram Bot API, llama.cpp (or llama-cpp-python) for GGUF SLM inference, Qwen3-4B-Instruct-2507 Q5_K_M GGUF, DeepSeek V4 Flash API, Hugging Face datasets / local JSONL for fine-tuning data.

---

## Global Constraints

- The approved design specs (`docs/superpowers/specs/2026-07-30-product-first-pilot-design.md` and `docs/superpowers/specs/2026-07-31-pilot-completion-remediation-design.md`) are authoritative.
- MVP surfaces are WebUI and Telegram only; do not add Zalo, public signup, billing, OAuth, or SLM serving until the pilot exit gate is passed.
- Reasoning, thinking blocks, tool arguments, paths, credentials, and raw provider errors cannot enter payloads, metadata, logs, responses, or metric labels.
- Capture, migration, and writer failures cannot retry a provider or prevent one final answer.
- The SLM teacher-student system is a **post-pilot milestone**. It must not delay the pilot exit gate.
- Distillation data is governed, reviewed, and never contains raw credentials or user identifiers.
- The SLM is always a secondary inference path; the teacher LLM remains the authoritative fallback.
- Use TDD. Do not complete a task without focused tests, Ruff, and relevant type/WebUI checks.

---

## Part 1: Completed Foundation (Tasks A.1–A.9)

These tasks are **already implemented and merged** into `develop`. They are listed here for completeness and should not be re-executed.

| Task | Description | Commit(s) | Status |
|------|-------------|-----------|--------|
| **A.1** | Typed pilot configuration and secure defaults | `33217b7d` | ✅ **Done** |
| **A.2** | Server-side presentation policy | `da35ca35` | ✅ **Done** (with known audit findings — see below) |
| **A.3** | Remove reasoning rendering from pilot clients | `c84063e0` | ✅ **Done** |
| **A.4** | Lock WebUI and Telegram ingress before side effects | `3ff06806` | ✅ **Done** |
| **A.5** | Compact stable turn identity | `5fbf20f3` | ✅ **Done** |
| **A.6** | Deterministic routing decisions | `9aad3291` | ✅ **Done** |
| **A.7** | Record provider attempts and harden retry classification | `f955913f` | ✅ **Done** |
| **A.8** | Model-scoped circuit breaking | `f50744d4` | ✅ **Done** |
| **A.9** | One-answer fallback delivery | `aa2bc225`, `f29e6752` | ✅ **Done** |

### Known audit remediation items (carried forward from code-audit-Task3.md)

These are accepted post-merge issues that must be resolved before starting Part 2:

- [ ] **Transcript reasoning code** — Review `nanobot/webui/transcript.py` functions (`attach_reasoning_chunk`, `close_reasoning`, `is_reasoning_only_placeholder`, `prune_reasoning_only`). Either remove them and update transcript replay to skip reasoning frames silently, or gate them behind a `reasoning_enabled` config flag that is `False` in pilot mode, or add explicit docstring comments documenting they are preserved only for legacy transcript replay.
- [ ] **`permits_event` ordering** — In `channels/manager.py` (`_send_once`), `permits_event` runs before `sanitize`. While functionally correct, add a comment explaining the intentional sequence. Optionally reorder for clarity.
- [ ] **Redaction pattern audit** — Review `PresentationPolicy` redaction patterns against the canary list from `code-audit-Task3.md`. Ensure coverage of: `reasoning_content`, `thinking_blocks`, reasoning event types, ` thinking... response` (both block and inline), bearer/API-key/cookie strings, Windows and POSIX internal paths, tool arguments, and raw exception text. Fix any over-broad patterns.
- [ ] **Ruff lint baseline** — Run `ruff check nanobot/pilot/` and resolve any remaining findings (24 reported in audit).
- [ ] **Checkbox reconciliation** — Update checkbox states in the archived plan (`2026-07-30-product-first-pilot-implementation-plan.md`) to reflect actual implementation status.

---

## Part 2: Capture & Storage (Tasks B.10–B.14)

These tasks implement the consent-gated capture pipeline: identity hashing, redaction, consent gates, capture queue, SQLite WAL store, capture hook, service lifecycle, and retention.

### Task B.10: HMAC identity, redaction, and capture gates

**Files:**
- Create: `nanobot/pilot/identity.py`
- Create: `nanobot/pilot/redaction.py`
- Create: `nanobot/pilot/consent.py`
- Create: `nanobot/pilot/types.py`
- Create: `tests/pilot/test_identity.py`
- Create: `tests/pilot/test_redaction.py`
- Create: `tests/pilot/test_consent.py`

- [ ] Implement `IdentityHasher` with `HMAC-SHA256(secret, f"{version}:{domain}:{value}")` returning hex digests; never retain the source value.
- [ ] Implement recursive `Redactor` for strings, mappings, and sequences. Return both redacted data and a set of rule codes; never return matched secret text in diagnostics.
- [ ] Implement `ConsentState` (product_allowed, training_allowed, versioned) and `CaptureDecision` (store_prompt/store_reasoning/store_answer/training_eligible) with three-gate logic: operator enabled, user consent, provider policy.
- [ ] Write failing tests for domain separation, secret rotation, no raw identity in repr, recursive map/list redaction, size bounds, and every operator/user/provider consent combination.
- [ ] Run: `uv run pytest tests/pilot/test_identity.py tests/pilot/test_redaction.py tests/pilot/test_consent.py -q`
- [ ] Commit: `git add nanobot/pilot/identity.py nanobot/pilot/redaction.py nanobot/pilot/consent.py nanobot/pilot/types.py tests/pilot`

### Task B.11: Build the prioritized bounded capture queue

**Files:**
- Create: `nanobot/pilot/queue.py`
- Create: `tests/pilot/test_capture_queue.py`

- [ ] Implement `CapturePriority` ordered as: `CONSENT`, `FEEDBACK`, `FINAL`, `ATTEMPT`, `ARTIFACT`.
- [ ] Use `asyncio.Condition` and a bounded heap/deque structure so a higher-priority event can evict the oldest lower-priority event when full.
- [ ] Expose content-free `QueueSnapshot(capacity, depth, dropped_by_kind, accepted_total)`.
- [ ] Write failing async tests for capacity, FIFO within priority, verbose-reasoning eviction, preservation of consent/feedback/final outcome/attempt metadata, depth/drop counters, blocked consumer wakeup, and bounded shutdown drain.
- [ ] Run: `uv run pytest tests/pilot/test_capture_queue.py -q`
- [ ] Commit: `git add nanobot/pilot/queue.py tests/pilot/test_capture_queue.py`

### Task B.12: Create the versioned SQLite WAL event store

**Files:**
- Create: `nanobot/pilot/migrations.py`
- Create: `nanobot/pilot/store.py`
- Create: `tests/pilot/test_store_migrations.py`
- Create: `tests/pilot/test_event_store.py`

**Schema (Migration 1):**
- `schema_migrations` — version tracking
- `turns` — pseudonymous identity, channel, timestamps, consent, routing decision (JSON)
- `attempts` — provider/model, latency_ms, usage (JSON), error_class, retry_index, fallback_index
- `artifacts` — redacted prompt, reasoning, answer, tool trajectory (as bounded JSON text)
- `feedback` — append-only user actions linked to turn_id
- `consents` — versioned consent state per pseudonym
- `deletions` — content-free audit records

- [ ] Migration 1 creates all tables with `PRAGMA journal_mode=WAL`, foreign keys, opaque event IDs as primary keys, UTC integer milliseconds, and JSON text for bounded sanitized structures.
- [ ] Implement `SQLitePilotStore` with synchronous transaction methods called only through `asyncio.to_thread` from a single writer. No store method may return artifacts for model-context construction.
- [ ] Add ownership lookup `(turn_id, user_pseudonym, session_pseudonym)`, consent lookup, aggregate metrics queries, deletion-by-pseudonym transaction, and dry-run retention counts.
- [ ] Write failing tests for migration from empty database, WAL mode, foreign keys, all six entities, append-only feedback, idempotent event IDs across reopen, database size, last successful write, and rollback on batch failure.
- [ ] Run: `uv run pytest tests/pilot/test_store_migrations.py tests/pilot/test_event_store.py -q`
- [ ] Commit: `git add nanobot/pilot/migrations.py nanobot/pilot/store.py tests/pilot/test_store_migrations.py tests/pilot/test_event_store.py`

### Task B.13: Add the isolated distillation capture hook and service lifecycle

**Files:**
- Create: `nanobot/pilot/capture.py`
- Create: `nanobot/pilot/service.py`
- Create: `nanobot/pilot/metrics.py`
- Create: `tests/pilot/test_capture_hook.py`
- Create: `tests/pilot/test_pilot_service.py`
- Modify: `nanobot/agent/hook.py`
- Modify: `nanobot/cli/commands.py`

- [ ] Implement `DistillationCaptureHook(AgentHook)` from `AgentTurnHookContext`. Accumulate per-iteration data, apply `CaptureDecision` and `Redactor`, then enqueue immutable events in `after_run`/`on_error`. Catch errors at the hook boundary and increment content-free failure metrics.
- [ ] Implement `PilotService.start()`, `hook_factory()`, `health_snapshot()`, and `stop()`. The writer consumes batches sequentially and calls `SQLitePilotStore.write_batch` through `asyncio.to_thread`.
- [ ] Wire in `nanobot/cli/commands.py`: create one service, append `pilot_service.hook_factory` to `hook_factories`, call `start()` before channels start, call `stop()` in shutdown `finally` block.
- [ ] Write failing tests showing the hook observes routing, approved prompt/context, provider/model generation settings, reasoning shapes, final answer, sanitized tool trajectory, attempts, usage, latency, and stop reason; assert it has no bus/channel reference and cannot publish outbound messages.
- [ ] Measure enqueue-path duration with a deliberately slow writer and assert the hook does not wait for persistence.
- [ ] Run: `uv run pytest tests/pilot/test_capture_hook.py tests/pilot/test_pilot_service.py tests/agent/test_hook_composite.py -q`
- [ ] Commit: `git add nanobot/pilot/capture.py nanobot/pilot/service.py nanobot/pilot/metrics.py tests/pilot nanobot/agent/hook.py nanobot/cli/commands.py`

### Task B.14: Add consent commands, revocation, deletion, and retention

**Files:**
- Modify: `nanobot/command/builtin.py`
- Create: `nanobot/pilot/retention.py`
- Create: `tests/pilot/test_privacy_commands.py`
- Create: `tests/pilot/test_retention.py`
- Modify: `nanobot/session/manager.py`
- Modify: `nanobot/webui/ws_http.py`

- [ ] Implement slash commands: `/consent status`, `/consent product on|off`, `/consent training on|off`, `/privacy delete`.
- [ ] Persist consent events at highest queue priority and maintain a small authoritative consent table via the writer.
- [ ] Implement deletion orchestration: block new capture for the pseudonym, delete session JSONL through `SessionManager`, delete artifacts/turns/feedback/consents transactionally, append content-free deletion audit.
- [ ] Add `RetentionService.plan(now)` and `apply(plan)` so dry-run/report and apply share the exact candidate IDs; exclude in-flight turn IDs supplied by `AgentLoop`.
- [ ] Write failing tests for separate versioned states, training default-off, revocation removing eligibility, and authorization scoped to the current sender/session.
- [ ] Run: `uv run pytest tests/pilot/test_privacy_commands.py tests/pilot/test_retention.py tests/agent/test_session_delete.py tests/webui/test_session_list_index.py -q`
- [ ] Commit: `git add nanobot/command/builtin.py nanobot/pilot/retention.py tests/pilot nanobot/session/manager.py nanobot/webui/ws_http.py`

---

## Part 3: User Controls, Feedback, Operations (Tasks C.15–C.17)

### Task C.15: Add transport-neutral feedback handling

**Files:**
- Create: `nanobot/pilot/feedback.py`
- Create: `tests/pilot/test_feedback.py`
- Modify: `nanobot/bus/events.py`
- Modify: `nanobot/bus/queue.py`
- Modify: `nanobot/agent/loop.py`

- [ ] Implement `FeedbackAction` (action_id, turn_id, kind, channel, sender_id, session_key) and `FeedbackAck` (action_id, accepted, reason) typed bus events.
- [ ] `FeedbackService.handle` must: HMAC channel identity, verify turn ownership in SQLite, append feedback idempotently, return acknowledgement, and for retry/explain publish a new `InboundMessage` only after authorization succeeds.
- [ ] Reconstruct retry input from authorized session history by `_pilot_turn_id`, not capture artifacts. For `explain_more`, create a fixed user-facing explanation request and strip `reasoning_content`/`thinking_blocks` from the replay context.
- [ ] Ensure feedback works when content capture is disabled (operational `turns` ownership rows are content-free and always retained).
- [ ] Write failing tests for all four actions, idempotency, owner denial, immutable original, no-capture ownership, retry_of, and explanation_of.
- [ ] Run: `uv run pytest tests/pilot/test_feedback.py tests/bus/test_outbound_events.py tests/session/test_turn_continuation.py -q`
- [ ] Commit: `git add nanobot/pilot/feedback.py tests/pilot/test_feedback.py nanobot/bus/events.py nanobot/bus/queue.py nanobot/agent/loop.py`

### Task C.16: Expose feedback in WebUI and Telegram

**Files:**
- Modify: `nanobot/channels/websocket/runtime.py`
- Modify: `nanobot/channels/telegram/runtime.py`
- Modify: `webui/src/lib/types.ts`
- Modify: `webui/src/lib/nanobot-client.ts`
- Modify: `webui/src/hooks/useNanobotStream.ts`
- Create: `webui/src/components/AssistantFeedbackActions.tsx`
- Modify: `webui/src/components/MessageBubble.tsx`
- Modify: `webui/src/i18n/locales/en/common.json`
- Modify: `webui/src/i18n/locales/vi/common.json`
- Create: `webui/src/tests/assistant-feedback-actions.test.tsx`
- Modify: `nanobot/channels/telegram/tests/test_telegram_channel.py`

- [ ] Add WebSocket envelope `type="feedback"` and response event `feedback_ack`. Route to `FeedbackService` without creating an agent turn for helpful/incorrect.
- [ ] Add Telegram inline keyboard to each accepted final answer using callback data `fb:<action-code>:<turn-id>`. Ignore/reject callbacks from another user.
- [ ] Render four accessible WebUI actions beneath completed assistant messages. Hide for streaming, command/system, and legacy messages without a turn ID.
- [ ] Write failing client tests for all four actions, stable `turn_id`, generated action IDs, disabled double-click, success/error acknowledgement, and P95-independent local optimistic state.
- [ ] Run: `cd webui && bun run test -- assistant-feedback-actions message-bubble nanobot-client useNanobotStream` and `cd .. && uv run pytest nanobot/channels/telegram/tests/test_telegram_channel.py tests/pilot/test_feedback.py -q`
- [ ] Commit: `git add nanobot/channels/websocket/runtime.py nanobot/channels/telegram/runtime.py nanobot/channels/telegram/tests/test_telegram_channel.py webui/src tests/pilot/test_feedback.py`

### Task C.17: Add sensitive-safe health and operational metrics

**Files:**
- Modify: `nanobot/pilot/metrics.py`
- Create: `nanobot/pilot/health.py`
- Create: `nanobot/webui/pilot_api.py`
- Create: `tests/pilot/test_metrics.py`
- Create: `tests/webui/test_pilot_api.py`
- Modify: `nanobot/webui/ws_http.py`
- Modify: `nanobot/webui/gateway_services.py`

- [ ] Implement bounded-label counters and fixed-bucket histograms. Allowed labels: channel, configured provider/model alias, route class, status/error class, policy version. Reject labels containing prompts, answers, reasoning, credentials, turn/session/user IDs, or arbitrary provider error text.
- [ ] Add authenticated `GET /api/pilot/health` and `GET /api/pilot/metrics` routes. Health has separate `agent`, `providers`, `channels`, and `capture_store` sections with `ok|degraded|down`.
- [ ] Compute D1/D7 and feedback distribution from aggregate SQL queries, never from metric labels containing identity.
- [ ] Write failing tests rejecting sensitive labels, testing health sections, and aggregate circuit/queue/cost/feedback/D1-D7/retention/DB fields.
- [ ] Run: `uv run pytest tests/pilot/test_metrics.py tests/webui/test_pilot_api.py tests/webui/test_settings_routes.py -q`
- [ ] Commit: `git add nanobot/pilot/metrics.py nanobot/pilot/health.py nanobot/webui/pilot_api.py tests/pilot/test_metrics.py tests/webui/test_pilot_api.py nanobot/webui/ws_http.py nanobot/webui/gateway_services.py`

---

## Part 4: Verification & Release (Tasks D.18–D.19)

### Task D.18: Add concurrency, performance, and leak regression gates

**Files:**
- Create: `tests/pilot/test_concurrent_turns.py`
- Create: `tests/pilot/test_capture_performance.py`
- Create: `tests/pilot/test_feedback_performance.py`
- Create: `tests/pilot/test_reasoning_leak_regression.py`
- Modify: `.github/workflows/ci.yml`

- [ ] Build a deterministic fake teacher that emits unique per-turn answer/reasoning canaries, tool calls, retries, and fallback outcomes.
- [ ] Run 20 active WebUI/Telegram turns and assert no session, stream, turn ID, reasoning, or feedback ownership mixing.
- [ ] Benchmark capture hook enqueue with a slow writer for enough iterations to calculate P95; assert added response-path latency ≤50 ms. Benchmark local feedback handling and assert P95 acknowledgement ≤1 s, excluding mocked channel transport.
- [ ] Capture logs, outbound payloads, WebSocket frames, Telegram calls, exception responses, and metric snapshots; assert every reasoning canary is absent.
- [ ] Add a dedicated CI job for pilot tests and WebUI leak tests.
- [ ] Run: `uv run pytest tests/pilot -q` and `cd webui && bun run test`
- [ ] Commit: `git add tests/pilot .github/workflows/ci.yml`

### Task D.19: Complete release verification and operator runbooks

**Files:**
- Create: `docs/pilot/configuration.md`
- Create: `docs/pilot/privacy-operations.md`
- Create: `docs/pilot/provider-failover.md`
- Create: `docs/pilot/staging-checklist.md`
- Create: `scripts/pilot_smoke.py`
- Create: `tests/pilot/test_smoke_script.py`

- [ ] Document complete configuration example using DeepSeek, Qwen/DashScope, Gemini API key, explicit fallback presets, finite WebUI/Telegram allowlists, reasoning disabled, capture gates, independent retention, cost ceiling, and alert thresholds.
- [ ] Document user consent/revocation/deletion, API-key rotation, capture disablement, SQLite backup/restore (including WAL checkpoint), retention dry-run/apply, provider shutdown, channel shutdown, and incident response for a reasoning leak.
- [ ] Implement read-only-by-default smoke script. `--fault-injection` uses configured fake endpoints and verifies retry/fallback/circuit. `--backup-restore` verifies store restoration without touching the live database.
- [ ] Run the complete local gate: `uv sync --all-extras --dev && uv run --no-sync python -m scripts.install_channel_dependencies --all-channels && uv run --no-sync ruff check nanobot tests scripts && uv run --no-sync basedpyright && uv run --no-sync pytest -q && cd webui && bun run test && bun run build`
- [ ] Commit: `git add docs/pilot scripts/pilot_smoke.py tests/pilot/test_smoke_script.py`

### Pilot Exit Gate (Operational, Not a Code Commit)

- [ ] All tasks in Parts 1–4 are merged and the full verification command is green.
- [ ] Security/privacy review has no unresolved high-severity issue.
- [ ] Privacy notice and Vietnamese/English consent text are approved by the operator.
- [ ] Finite invite/allowlists and a named pilot-support owner are recorded.
- [ ] Daily provider cost ceiling and alert are active.
- [ ] Fault injection demonstrates retry, fallback, circuit open/cooldown, and one-answer delivery.
- [ ] SQLite backup and restore complete successfully against a staging copy.
- [ ] Staging runs continuously for 72 hours with no reasoning canary leak, task/process leak, or capture-caused chat outage.
- [ ] D1/D7 retention, answer success rate, latency, feedback, provider cost, queue drops, and writer health are reviewed before admitting pilot users.

---

## Part 5: SLM Distillation & Teacher-Student Architecture (NEW)

> **Prerequisite:** Parts 1–4 must be complete and the pilot exit gate must be passed. This milestone is a **post-pilot** addition that builds on the captured reasoning traces. The detailed implementation plan lives in a separate sub-plan file.

### Referenced Sub-Plan

See **`docs/superpowers/plans/2026-08-07-pilot-slm-distillation-plan.md`** for the full implementation of Tasks E.20–E.26.

### Summary

| Task | Description | Key Files |
|------|-------------|-----------|
| **E.20** | Data curation pipeline from SQLite store | `scripts/pilot_export.py`, `scripts/pilot_curate.py` |
| **E.21** | Format conversion for fine-tuning | `scripts/pilot_prepare_ft.py` |
| **E.22** | Fine-tune Qwen3-4B-Instruct on curated reasoning data | `scripts/pilot_finetune.py`, `scripts/pilot_finetune_config.yaml` |
| **E.23** | SLM inference service with llama.cpp | `nanobot/providers/student_provider.py`, `nanobot/pilot/student.py` |
| **E.24** | Teacher-Student orchestration and complexity classifier | `nanobot/pilot/orchestrator.py`, `nanobot/pilot/complexity.py` |
| **E.25** | Evaluation benchmarks for SLM quality | `scripts/pilot_evaluate.py` |
| **E.26** | SLM-specific configuration, routing, and telemetry | modifications to `metrics.py`, `health.py`, `config/schema.py` |

**Architecture (high-level):**

```
User message → TaskComplexityClassifier
  ├─ Simple → SLM (Qwen3-4B Q5_K_M) answers directly
  └─ Complex → SLM generates plan → Teacher (DeepSeek V4 Flash) reviews
                ├─ Approved → Execute plan
                ├─ Revised → SLM revises (max 2 rounds)
                └─ Rejected → Fall back to teacher-only execution
```

**Dependency chain:**

```
E.20 Data Curation ──► E.21 Format Conversion ──► E.22 Fine-tune Qwen3-4B
                                                          │
                                                          ▼
                                                    E.23 SLM Inference
                                                          │
                                              ┌───────────┼───────────┐
                                              ▼           ▼           ▼
                                         E.24 Teacher-   E.25         E.26
                                         Student         Evaluation   Telemetry
                                         Orchestrator
```

---

## Acceptance Traceability

| Requirement | Part/Task | Required Evidence |
|-------------|-----------|-------------------|
| Access and reasoning confidentiality | Part 1, Tasks A.1–A.5, D.18 | Canary tests, unauthorized-side-effect tests, reasoning leak regressions |
| Configured routing and resilience | Part 1, Tasks A.6–A.9 | Determinism tables, circuit fake-clock tests, one-answer integration |
| Consent-gated capture | Part 2, Tasks B.10–B.14 | Gate matrix, HMAC/redaction tests, revocation/deletion integration |
| Capture queue and store | Part 2, Tasks B.11–B.13 | Priority pressure tests, WAL/migration/restart tests, capture isolation |
| Feedback | Part 3, Tasks C.15–C.16 | Ownership/idempotency/link tests on WebUI and Telegram |
| Retention and observability | Part 2, Task B.14; Part 3, Task C.17 | Dry-run/apply equivalence, safe-label tests, health snapshots |
| Performance | Part 3, Tasks C.15–C.16; Part 4, D.18 | Capture P95, feedback P95, slow-writer and 20-turn concurrency |
| Required verification | Part 4, Tasks D.18–D.19 | Full Python/WebUI/type/lint/build results and staging checklist |
| Data curation | Part 5, Task E.20 | Export rejects ineligible rows, no credentials, deduplication |
| Fine-tuning | Part 5, Tasks E.21–E.22 | Format correctness, LoRA structure, GGUF export |
| SLM inference | Part 5, Task E.23 | Prompt format, streaming, token counting, concurrent isolation |
| Teacher-student orchestration | Part 5, Task E.24 | Complexity classification, plan generation, teacher review, fallback |
| Evaluation | Part 5, Task E.25 | Metric computation, baseline results, cost/latency comparison |

---

## Dependency Graph

```
Part 1 (Foundation) ──► Audit Remediation ──► Part 2 (Capture & Store)
                                                      │
                                                      ▼
                                              Part 3 (Feedback, Ops)
                                                      │
                                                      ▼
                                              Part 4 (Verification, Release)
                                                      │
                                              Pilot Exit Gate
                                                      │
                                                      ▼
                                    ┌─────────────────────────────────┐
                                    │  Part 5 (SLM Distillation)      │
                                    │  docs/superpowers/plans/        │
                                    │  2026-08-07-pilot-slm-          │
                                    │  distillation-plan.md           │
                                    └─────────────────────────────────┘
```

## Deferred Follow-on Plans

Create separate design/implementation plans only after the pilot exit gate and SLM milestone are complete:

1. Unofficial `openzalo`/Zalo Personal channel isolation and account-risk controls.
2. Public signup, quotas, and billing.
3. Operator-owned Gemini OAuth experiments.
4. Multi-SLM ensemble routing.
5. Automated data labeling and reward model training.
6. Continuous fine-tuning pipeline with online data collection.

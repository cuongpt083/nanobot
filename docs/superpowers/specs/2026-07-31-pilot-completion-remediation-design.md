# Pilot Completion and Remediation Design

**Status:** Proposed supplement to the approved 2026-07-30 product-first pilot design

## 1. Purpose and scope

This supplement turns the approved product design into an executable completion target after the 2026-07-31 repository audit. The original product design remains authoritative for product requirements. This document supersedes the archived implementation plan and Task 3 audit as the technical baseline for remaining work.

Scope includes production code, automated verification, operator runbooks, smoke tooling, and staging evidence required for the invite-only WebUI and Telegram pilot. It does not add Zalo, Gemini OAuth, public signup, billing, training export, or model serving.

## 2. Delivery model

Work is delivered in five sequential milestones. A milestone may be merged only when its focused tests, lint, strict type checks for changed code, and relevant WebUI checks pass. No milestone may weaken privacy tests to make an implementation pass.

1. **Foundation remediation:** make routing configuration effective and harden the presentation boundary.
2. **Provider resilience:** add provider/model-scoped circuit state and guarantee one terminal answer.
3. **Private capture foundation:** add identity hashing, redaction, consent gates, queue, WAL store, and capture lifecycle.
4. **User controls and operations:** add consent/deletion/retention, feedback, and safe health/metrics.
5. **Release evidence:** add regression gates, runbooks, smoke/backup-restore tooling, and staging evidence.

## 3. Foundation remediation

`PilotModelClassConfig.preset` is the sole configured preset field. The router returns that value for the selected route class; it never returns route-class labels. Routing receives a read-only circuit snapshot, filters unavailable candidates before choosing a primary, and produces only fixed reason codes. The loop resolves the returned preset before context construction.

The presentation guard is the only outbound payload boundary for WebUI and Telegram. It operates on a copied `OutboundMessage` and recursively sanitizes content and all metadata values. It rejects reasoning events before content processing when display is disabled; removes complete and unclosed `<think>` blocks; drops case-normalized reasoning, tool, error, and diagnostics keys; and redacts credentials, URL credentials, private-key blocks, cookies, and Windows/POSIX paths at every nesting depth. It increments only content-free leak-prevention metrics. Legacy reasoning frames remain inert compatibility input and cannot create client text, metadata, or activity state.

## 4. Provider resilience

`CircuitRegistry` is a process-level, lock-protected service keyed by configured provider alias and model. It exposes a content-free snapshot and supports closed, open, and single-probe half-open states using an injected monotonic clock. Authentication errors open immediately; retryable failures open only after the configured threshold. The router and fallback provider share this registry.

Fallback attempts are buffered until an acceptable response segment exists. Once any final answer is accepted, no fallback may emit another final answer. If every candidate is unavailable, the system sends one short presentation-sanitized error. Capture-hook failures are capture health failures only and never alter provider retry or fallback behavior.

## 5. Private capture and persistence

Capture is independent of sessions and message delivery. `IdentityHasher` returns versioned, domain-separated HMAC-SHA256 hex pseudonyms. `Redactor` recursively returns a bounded sanitized value plus rule codes; it never returns the matched secret.

`CaptureDecision` permits artifact fields only if all three gates pass: operator capture enabled, current user consent for the requested use, and configured provider capture policy. Denied capture still records content-free turn and attempt metrics needed for ownership, reliability, and feedback.

The bounded `CaptureQueue` prioritizes `CONSENT`, `FEEDBACK`, `FINAL`, `ATTEMPT`, and `ARTIFACT` in that order. A single `SQLitePilotStore` writer uses WAL, foreign keys, versioned migrations, opaque idempotency keys, and `asyncio.to_thread`. It persists only pseudonymous bounded JSON and has no API for model-context reads. Migration and writer errors make capture degraded while chat stays usable.

`DistillationCaptureHook` only observes lifecycle data and queue events; it has no bus or channel reference. `PilotService` owns start, hook factory, writer, health snapshot, bounded stop/flush, and unpersisted-count reporting without content logging.

## 6. User controls, feedback, and operations

Consent has separate, versioned product-improvement and future-training values. Future training is off until expressly enabled. Revocation immediately removes training eligibility. Deletion blocks new capture for the identity, deletes matching session and pilot data transactionally, and records only a content-free deletion audit. Retention has deterministic `plan(now)` and `apply(plan)` operations; it supports dry-run and excludes in-flight turns.

Feedback uses typed bus actions and stable turn IDs. `helpful` and `incorrect` append idempotently. `retry` and `explain_more` authorize ownership first, then create linked user turns from session history, never from capture artifacts. The explanation request is fixed and uses a replay context with reasoning fields removed. WebUI renders accessible actions only for completed assistant messages with a turn ID; Telegram uses compact callback data and rejects cross-user callbacks.

Metrics and health use bounded safe labels only. Authenticated pilot endpoints provide separate agent, provider, channel, and capture-store health plus aggregate metrics, including circuit, queue/writer, cost, feedback, D1/D7, retention, database size, and last successful write.

## 7. Verification and release evidence

The test suite must include reasoning canaries across payloads, metadata, logs, exceptions, metrics, WebSocket frames, and Telegram calls; fault-injected retry/fallback/circuit paths; SQLite migration and restart idempotency; authorization and deletion; 20 concurrent turns; capture P95 at or below 50 ms; and local feedback acknowledgement P95 at or below one second.

Runbooks document safe configuration, consent/revocation/deletion, API-key rotation, capture disablement, backup/restore and WAL checkpoint, retention dry-run/apply, provider/channel shutdown, reasoning-leak response, finite invite ownership, daily cost ceiling, and alert thresholds. The smoke tool is read-only by default; fault injection uses fake endpoints only; backup/restore operates only on an explicit temporary directory.

Code completion is not pilot admission. Admission additionally requires green full verification, approved privacy notice and consent copy, configured finite allowlists/cost alert, successful staging backup/restore and fault injection, and 72 consecutive staging hours without capture-caused outage, reasoning leak, or task/process leak.

## 8. Archive policy

The prior implementation plan and Task 3 audit are retained under `docs/superpowers/archive/2026-07-31-pilot-remediation/` for traceability. The approved original product design remains active; this supplement and the forthcoming completion plan replace the old execution sequencing.

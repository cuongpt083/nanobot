# Pilot Completion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Complete the invite-only WebUI and Telegram pilot with private reasoning, reliable provider execution, consent-gated capture, user controls, operational tooling, and release evidence.

**Architecture:** Preserve AgentLoop, AgentRunner, session JSONL, and current channel/provider contracts as the chat path. Add narrow pilot services for routing/circuit, capture/privacy/store, feedback/retention, and health. Capture and persistence failures must be isolated from message delivery.

**Tech Stack:** Python 3.11+, asyncio, Pydantic, stdlib sqlite3, pytest/pytest-asyncio, Ruff, basedpyright, React 18, TypeScript, Vite, Vitest, Telegram Bot API.

## Global Constraints

- The approved 2026-07-30 product design and 2026-07-31 supplement are authoritative.
- MVP surfaces are WebUI and Telegram only; do not add Zalo, public signup, billing, OAuth, training export, or SLM serving.
- Reasoning, thinking blocks, tool arguments, paths, credentials, and raw provider errors cannot enter payloads, metadata, logs, responses, or metric labels.
- Capture, migration, and writer failures cannot retry a provider or prevent one final answer.
- Use TDD. Do not complete a task without focused tests, Ruff, and relevant type/WebUI checks.
- Preserve the existing untracked tests/pilot/__init__.py unless its owner asks to include it.

## File map

| Area | Files | Responsibility |
| --- | --- | --- |
| Foundation | nanobot/pilot/presentation.py, routing.py, agent/loop.py, channels/manager.py | safe outbound policy and configured routing |
| Resilience | nanobot/pilot/circuit.py, providers/fallback_provider.py, agent/turn_delivery.py | circuit state and one-answer failover |
| Capture | identity.py, redaction.py, consent.py, queue.py, store.py, capture.py, service.py | pseudonymous asynchronous capture |
| Controls | retention.py, feedback.py, bus/channel/WebUI files | deletion, retention, feedback |
| Operations | metrics.py, health.py, webui/pilot_api.py, scripts/pilot_smoke.py, docs/pilot | safe health and release procedures |

---

### Task 1: Repair configured routing and presentation policy

**Files:** Modify nanobot/pilot/routing.py, presentation.py, channels/manager.py, agent/loop.py; modify tests/pilot/test_routing.py, test_presentation.py, tests/channels/test_channel_manager_reasoning.py; create tests/pilot/test_routing_loop.py.

**Interfaces:** route_turn(turn_id, input_data, config, circuit=None) returns RoutingDecision. PresentationPolicy.sanitize(content, metadata) returns a copied PresentationResult and never mutates an input.

- [ ] Write failing AgentLoop tests using a real Config whose route presets are fast, reasoner, and tools. Assert each route resolves the configured preset rather than a route label.
- [ ] Write parameterized canaries for nested provider_error, arguments, toolArguments, bearer/API key/cookie/private-key strings, URL credentials, POSIX/Windows paths, and unclosed think tags in both content and metadata.
- [ ] Run: ~~~bash
uv run pytest tests/pilot/test_routing.py tests/pilot/test_routing_loop.py tests/pilot/test_presentation.py tests/channels/test_channel_manager_reasoning.py -q
~~~
Expected before implementation: routing-loop test fails because primary_preset is read instead of preset.
- [ ] Use class_cfg.preset; filter open candidates from an immutable circuit snapshot. Recursively normalize metadata keys, drop policy keys, redact string leaves, and send dataclasses.replace(msg, ...) instead of mutating msg. Drop reasoning events before sanitizer when display is disabled.
- [ ] Re-run the command above plus: ~~~bash
uv run ruff check nanobot/pilot/routing.py nanobot/pilot/presentation.py nanobot/channels/manager.py
~~~
- [ ] Commit: ~~~bash
git add nanobot/pilot/routing.py nanobot/pilot/presentation.py nanobot/channels/manager.py nanobot/agent/loop.py tests/pilot tests/channels/test_channel_manager_reasoning.py
git commit -m "fix(pilot): enforce configured routing and presentation policy"
~~~

### Task 2: Add provider/model circuit registry

**Files:** Create nanobot/pilot/circuit.py and tests/pilot/test_circuit.py. Modify routing.py and providers/fallback_provider.py.

**Interfaces:** CircuitRegistry(clock, failure_threshold, cooldown_seconds), allow(key), record_success(key), record_failure(key, error_class), snapshot(). CircuitKey is provider alias plus model only.

- [ ] Write fake-clock tests for closed-open-half-open-closed, provider/model isolation, one half-open probe, retry threshold, cooldown, and immediate authentication open.
- [ ] Run: ~~~bash
uv run pytest tests/pilot/test_circuit.py -q
~~~
Expected: import failure.
- [ ] Implement lock-protected state with no prompt/user fields. Inject one registry into router and fallback provider; omit open primary/fallback candidates and update state after each attempt.
- [ ] Add all-open integration test asserting one generic sanitized error and no provider alias in user output.
- [ ] Verify and commit: ~~~bash
uv run pytest tests/pilot/test_circuit.py tests/pilot/test_routing.py tests/agent/test_runner_fallback.py -q
git add nanobot/pilot/circuit.py nanobot/pilot/routing.py nanobot/providers/fallback_provider.py tests/pilot/test_circuit.py
git commit -m "feat(pilot): add model scoped circuit breaking"
~~~

### Task 3: Guarantee one-answer fallback delivery

**Files:** Modify providers/fallback_provider.py and agent/turn_delivery.py. Create tests/pilot/test_fallback_delivery.py.

**Interfaces:** A turn accepts at most one final delivery segment; fallback output is buffered until an accepted boundary.

- [ ] Write fake-provider tests for failure before stream, timeout after partial stream, non-timeout after content, exhausted chain, all-open chain, and capture-hook exception. Count final outbound messages.
- [ ] Run the focused test and confirm failure.
- [ ] Buffer fallback candidate output; discard unaccepted primary fragments; lock TurnDelivery after first accepted final. Use a fixed PresentationPolicy-sanitized error for exhaustion. Capture-hook exception only increments capture health.
- [ ] Verify and commit: ~~~bash
uv run pytest tests/pilot/test_fallback_delivery.py tests/agent/test_runner_fallback.py tests/agent/test_turn_delivery.py -q
git add nanobot/providers/fallback_provider.py nanobot/agent/turn_delivery.py tests/pilot/test_fallback_delivery.py
git commit -m "fix(pilot): guarantee one answer during failover"
~~~

### Task 4: Add identity, redaction, and capture gates

**Files:** Create nanobot/pilot/identity.py, redaction.py, consent.py, tests/pilot/test_identity.py, test_redaction.py, test_capture_decision.py. Modify config/schema.py.

**Interfaces:** IdentityHasher.pseudonym(domain, value) returns a versioned HMAC hex digest. Redactor.redact(value, max_chars) returns sanitized value and rule codes. CaptureDecision.for_turn(config, consent, policy) returns field permissions.

- [ ] Write tests for domain separation, secret rotation, no raw identity in repr, recursive map/list redaction, size bounds, and every operator/user/provider consent combination.
- [ ] Run focused tests and confirm missing imports.
- [ ] Implement HMAC-SHA256 over version:domain:value; redact credentials, cookies, private keys, URL credentials, and POSIX/Windows paths before truncation. Add bounded circuit/capture policy config fields.
- [ ] Verify and commit: ~~~bash
uv run pytest tests/pilot/test_identity.py tests/pilot/test_redaction.py tests/pilot/test_capture_decision.py tests/config/test_pilot_config.py -q
uv run ruff check nanobot/pilot/identity.py nanobot/pilot/redaction.py nanobot/pilot/consent.py nanobot/config/schema.py
git add nanobot/pilot/identity.py nanobot/pilot/redaction.py nanobot/pilot/consent.py nanobot/config/schema.py tests/pilot
git commit -m "feat(pilot): add private identity redaction and capture gates"
~~~

### Task 5: Build capture queue and SQLite WAL store

**Files:** Create nanobot/pilot/queue.py, store.py, tests/pilot/test_capture_queue.py, test_store.py.

**Interfaces:** CaptureQueue.put(event), get(), snapshot(); priorities are CONSENT, FEEDBACK, FINAL, ATTEMPT, ARTIFACT. SQLitePilotStore.write_batch, lookup_owner, consent_for, delete_identity.

- [ ] Write queue tests for bounded capacity, FIFO per priority, oldest-lower-priority eviction, drops, consumer wakeup, and bounded drain. Write temporary-SQLite tests for WAL, foreign keys, migrations, six entities, rollback, and restart idempotency.
- [ ] Run focused tests and confirm imports fail.
- [ ] Implement asyncio.Condition queue with monotonic sequence. Add migration 1 tables schema_migrations, turns, attempts, artifacts, feedback, consents, deletions; persist bounded pseudonymous JSON and opaque event IDs only.
- [ ] Ensure the store has no artifact-read API for model context and all caller usage will be via asyncio.to_thread.
- [ ] Verify and commit: ~~~bash
uv run pytest tests/pilot/test_capture_queue.py tests/pilot/test_store.py -q
uv run ruff check nanobot/pilot/queue.py nanobot/pilot/store.py
git add nanobot/pilot/queue.py nanobot/pilot/store.py tests/pilot
git commit -m "feat(pilot): add prioritized capture queue and WAL store"
~~~

### Task 6: Add isolated capture hook and service lifecycle

**Files:** Create nanobot/pilot/capture.py, service.py, tests/pilot/test_capture_hook.py, test_pilot_service.py. Modify agent/hook.py and cli/commands.py.

**Interfaces:** DistillationCaptureHook(AgentHook) observes lifecycle only. PilotService.start(), hook_factory(), health_snapshot(), stop() own writer lifecycle.

- [ ] Write tests that feed routing, prompt/context, provider reasoning, answer, sanitized tool results, attempts, usage, latency, and stop reason; assert hook has no MessageBus/channel reference.
- [ ] Add a slow-writer test proving enqueue returns without persistence wait and a migration-failure test proving chat-ready degraded service.
- [ ] Implement immutable queued events after CaptureDecision and Redactor; catch hook exceptions into content-free metrics. Bootstrap one service before channels, append hook factory to AgentLoop, and stop it after channels.
- [ ] Verify and commit: ~~~bash
uv run pytest tests/pilot/test_capture_hook.py tests/pilot/test_pilot_service.py tests/agent/test_runner_fallback.py -q
git add nanobot/pilot/capture.py nanobot/pilot/service.py nanobot/agent/hook.py nanobot/cli/commands.py tests/pilot
git commit -m "feat(pilot): isolate distillation capture lifecycle"
~~~

### Task 7: Add consent, deletion, and retention controls

**Files:** Create nanobot/pilot/retention.py, tests/pilot/test_privacy_commands.py, test_retention.py. Modify command/builtin.py, session/manager.py, webui/ws_http.py, pilot/service.py.

**Interfaces:** RetentionService.plan(now_ms, in_flight_turn_ids) returns RetentionPlan; apply(plan) returns RetentionResult. PilotService.delete_identity(channel, sender_id, session_key) returns DeletionResult.

- [ ] Write command tests for consent status/product/training and privacy delete; assert training default off, stale consent denies content, repeat deletion succeeds, and audit contains no content.
- [ ] Write retention dry-run/apply equivalence test with an in-flight turn excluded.
- [ ] Implement scoped authorization, highest-priority consent events, capture blocking before delete, session deletion plus transactional pilot delete, and WebUI reuse of the same service.
- [ ] Verify and commit: ~~~bash
uv run pytest tests/pilot/test_privacy_commands.py tests/pilot/test_retention.py tests/agent/test_session_delete.py tests/webui/test_session_list_index.py -q
git add nanobot/pilot/retention.py nanobot/command/builtin.py nanobot/session/manager.py nanobot/webui/ws_http.py nanobot/pilot/service.py tests/pilot
git commit -m "feat(pilot): add consent deletion and retention controls"
~~~

### Task 8: Add transport-neutral feedback service

**Files:** Create nanobot/pilot/feedback.py, tests/pilot/test_feedback.py. Modify bus/events.py, bus/queue.py, agent/loop.py, pilot/store.py.

**Interfaces:** FeedbackAction(action_id, turn_id, kind, channel, sender_id, session_key); FeedbackAck(action_id, accepted, reason); FeedbackService.handle(action).

- [ ] Write tests for helpful, incorrect, retry, explain_more, idempotency, owner denial, immutable original, no-capture ownership, retry_of, and explanation_of.
- [ ] Implement pseudonymous owner lookup and append-only feedback. Publish replacement inbound work only after authorization. Rebuild retry from scoped session history by _pilot_turn_id; explanation is a fixed request with reasoning fields removed.
- [ ] Verify and commit: ~~~bash
uv run pytest tests/pilot/test_feedback.py tests/bus/test_outbound_events.py tests/session/test_turn_continuation.py -q
git add nanobot/pilot/feedback.py nanobot/bus/events.py nanobot/bus/queue.py nanobot/agent/loop.py nanobot/pilot/store.py tests/pilot
git commit -m "feat(pilot): add scoped feedback workflow"
~~~

### Task 9: Expose feedback in WebUI and Telegram

**Files:** Create webui/src/components/AssistantFeedbackActions.tsx and its test. Modify websocket/telegram runtime, WebUI types/client/stream hook/MessageBubble/locales, and Telegram tests.

**Interfaces:** WebSocket feedback envelope returns feedback_ack. Telegram callback data is fb:action:turn-id.

- [ ] Write WebUI tests for four actions, generated IDs, disabled double-click, optimistic state, and hidden streaming/system/legacy messages. Write Telegram keyboard/ownership/acknowledgement tests.
- [ ] Route helpful/incorrect without a new turn; dispatch retry/explain after service authorization. Render accessible completed-message actions and reject foreign Telegram callbacks before persistence.
- [ ] Verify and commit: ~~~bash
cd webui && bun run test -- assistant-feedback-actions message-bubble nanobot-client useNanobotStream
cd .. && uv run pytest nanobot/channels/telegram/tests/test_telegram_channel.py tests/pilot/test_feedback.py -q
git add nanobot/channels/websocket/runtime.py nanobot/channels/telegram/runtime.py webui/src tests/pilot
git commit -m "feat(pilot): expose feedback in webui and telegram"
~~~

### Task 10: Add safe metrics, health, and operator API

**Files:** Create pilot/metrics.py, health.py, webui/pilot_api.py, tests/pilot/test_metrics.py, tests/webui/test_pilot_api.py. Modify webui/ws_http.py, gateway_services.py, pilot/service.py.

**Interfaces:** PilotMetrics.increment/observe/snapshot; authenticated GET /api/pilot/health and /api/pilot/metrics.

- [ ] Write tests rejecting sensitive labels and allowing only channel, provider/model alias, route class, status class, policy version. Test health sections and aggregate circuit/queue/cost/feedback/D1-D7/retention/DB fields.
- [ ] Implement fixed buckets/counters and aggregate SQL queries; apply existing operator auth and emit no raw diagnostics.
- [ ] Verify and commit: ~~~bash
uv run pytest tests/pilot/test_metrics.py tests/webui/test_pilot_api.py tests/webui/test_settings_routes.py -q
git add nanobot/pilot/metrics.py nanobot/pilot/health.py nanobot/webui/pilot_api.py nanobot/webui/ws_http.py nanobot/webui/gateway_services.py tests/pilot tests/webui
git commit -m "feat(pilot): expose privacy safe health and metrics"
~~~

### Task 11: Add concurrency, performance, and leak regression gates

**Files:** Create tests/pilot/test_concurrent_turns.py, test_capture_performance.py, test_feedback_performance.py, test_reasoning_leak_regression.py. Modify .github/workflows/ci.yml.

- [ ] Build one deterministic fake teacher with unique answer/reasoning canaries, retries, fallback, and tools.
- [ ] Write 20 concurrent WebUI/Telegram turn assertions for no session/stream/turn/feedback/reasoning mixing. Capture logs, frames, Telegram calls, exceptions, and metrics; assert every reasoning canary is absent.
- [ ] Add slow-writer fake-clock P95 test at 50 ms and local feedback P95 test at one second. Add dedicated CI job.
- [ ] Verify and commit: ~~~bash
uv run pytest tests/pilot -q
uv run pytest tests/pilot/test_concurrent_turns.py tests/pilot/test_reasoning_leak_regression.py -q
cd webui && bun run test
git add tests/pilot .github/workflows/ci.yml
git commit -m "test(pilot): add privacy concurrency and performance gates"
~~~

### Task 12: Write runbooks and smoke tooling

**Files:** Create docs/pilot/configuration.md, privacy-operations.md, provider-failover.md, staging-checklist.md, scripts/pilot_smoke.py, tests/pilot/test_smoke_script.py.

**Interfaces:** python scripts/pilot_smoke.py --config path is read-only. Fault injection accepts fake endpoints only; backup-restore accepts an empty temporary directory only.

- [ ] Write smoke tests proving default mode does not write, fake fault injection verifies retry/fallback/circuit, and backup/restore refuses live DB paths.
- [ ] Document env-placeholder configuration, finite allowlists, reasoning disabled, capture gates, retention, cost ceiling, consent/revocation/deletion, key rotation, WAL backup/restore, retention, shutdown, and leak response.
- [ ] Add staging checklist fields for commands/results, privacy approval, support owner, fault injection, backup/restore, costs, and 72-hour observation.
- [ ] Verify and commit: ~~~bash
uv run pytest tests/pilot/test_smoke_script.py -q
uv run ruff check scripts/pilot_smoke.py
git add docs/pilot scripts/pilot_smoke.py tests/pilot/test_smoke_script.py
git commit -m "docs(pilot): add operational runbooks and smoke verification"
~~~

### Task 13: Execute full engineering and release gate

**Files:** Modify docs/pilot/staging-checklist.md only after each evidence item is complete.

- [ ] Install Bun and record bun --version, Python, and uv versions.
- [ ] Run: ~~~bash
uv sync --all-extras --dev
uv run --no-sync python -m scripts.install_channel_dependencies --all-channels
uv run --no-sync ruff check nanobot tests scripts
uv run --no-sync basedpyright
uv run --no-sync pytest -q
cd webui && bun run test && bun run build
~~~
- [ ] Run smoke fault injection and backup/restore against only disposable staging resources; record timestamp, command, result, and artifact paths without credentials.
- [ ] Operate staging 72 continuous hours with finite allowlists and cost alert. Record daily provider/capture health, queue drops, reasoning-leak scans, and task/process health.
- [ ] Confirm approved Vietnamese/English privacy and consent text, named support owner, and no unresolved high-severity issue.
- [ ] Commit completed evidence: ~~~bash
git add docs/pilot/staging-checklist.md
git commit -m "docs(pilot): record pilot exit gate evidence"
~~~

## Acceptance traceability

| Requirement | Tasks |
| --- | --- |
| Access and reasoning confidentiality | 1, 9, 11 |
| Configured routing and resilience | 1, 2, 3 |
| Consent, identity, queue, WAL store | 4, 5, 6 |
| Deletion, retention, feedback | 7, 8, 9 |
| Safe metrics and health | 10 |
| Performance, concurrency, leak absence | 11 |
| Runbooks, smoke, staging exit gate | 12, 13 |

## Plan self-review

- Coverage: every supplement section has at least one task.
- Scope: no deferred non-goal is introduced.
- Dependency order: capture gates precede hook; queue/store precede service; service/store precede controls and feedback; feedback precedes UI; metrics precede release evidence.
- Verification: each implementation task contains focused tests, commands, and a commit boundary.


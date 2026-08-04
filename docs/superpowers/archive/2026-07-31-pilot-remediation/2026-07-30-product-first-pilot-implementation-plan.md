# Product-First Pilot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver an invite-only WebUI and Telegram pilot that keeps provider reasoning private, routes requests deterministically across configured teacher models, survives provider failures, and records consent-gated interaction data for future distillation without putting chat availability at risk.

**Architecture:** Preserve `AgentLoop`, `AgentRunner`, session JSONL, and existing channel/provider contracts as the product path. Add policy at the channel boundary, a deterministic per-turn runtime selector before context construction, and an isolated `nanobot.pilot` service registered through turn hooks. The pilot service owns HMAC identity, consent, capture queue, SQLite WAL persistence, feedback, retention, health, and metrics; its failures are always non-fatal to message delivery.

**Tech Stack:** Python 3.11+, asyncio, Pydantic, stdlib `sqlite3`, pytest/pytest-asyncio, basedpyright, Ruff, React 18, TypeScript, Vite, Vitest, Telegram Bot API.

## Progress audit — 2026-08-04

This audit compares the plan with the current `develop` tree, source files, pilot tests, and Git history. It is a status update only; the task checkboxes below remain the implementation checklist.

**Repository baseline:** `develop` and `origin/develop` are synchronized at `6d45b5e3` (`Merge pull request #4 from cuongpt083/feature/product-first-pilot`).

| Workstream | Tasks | Current status | Evidence / next action |
| --- | --- | --- | --- |
| A. Confidential pilot boundary | 1–5 | **Implemented** | `nanobot/config/schema.py`, `nanobot/pilot/presentation.py`, `nanobot/pilot/turns.py`, channel ingress changes, WebUI reasoning removal, and focused pilot/channel tests are present. Task 4/5 implementation commits are represented in the merged history even though their commit checklist bullets were not checked. |
| B. Routing and provider resilience | 6–9 | **Implemented** | `nanobot/pilot/routing.py`, `nanobot/pilot/circuit.py`, provider-attempt instrumentation, structured fallback handling, and `tests/pilot/test_circuit.py` / `test_fallback_delivery.py` are present. |
| C. Consent-gated capture | 10–14 | **Not started** | No `IdentityHasher`, `Redactor`, bounded capture queue, SQLite pilot store, `PilotService`, consent/deletion, or retention implementation is present under `nanobot/pilot`. |
| D. Feedback, operations, and release gate | 15–19 | **Not started** | No pilot feedback service/UI actions, authenticated pilot health/metrics endpoints, concurrency/leak gates, staging checklist evidence, or operator runbooks for this plan are present. |

### Verification status

- Static/source audit: implementation evidence found for Tasks 1–9.
- Focused/full automated verification: **pending**. The current environment cannot start `pytest` or `ruff` (`program not found` / no `pytest` module), so no test-pass claim is recorded here.
- The next completion gate is to install/supply the project test dependencies, run the Task 1–9 focused suites plus the full suite, and then execute Tasks 10–19.

### Remaining delivery scope

1. Complete Tasks 10–14: pseudonymous identity and redaction, priority capture queue, SQLite WAL store, isolated capture lifecycle, consent/revocation/deletion, and retention.
2. Complete Tasks 15–17: transport-neutral feedback, WebUI/Telegram feedback UX, sensitive-safe health and metrics.
3. Complete Tasks 18–19: concurrency/performance/leak gates, CI job, release verification, staging evidence, and operator runbooks.
4. Update the individual task checkboxes and add command/commit evidence after each verification gate passes.

## Global Constraints

- The approved design in `docs/superpowers/specs/2026-07-30-product-first-pilot-design.md` is authoritative.
- MVP channels are WebUI and Telegram. Do not add Zalo or Gemini OAuth in this plan.
- Gemini uses API-key provider configuration only.
- Raw `reasoning_content`, `thinking_blocks`, `<think>` content, tool arguments, internal paths, and raw provider errors must not cross a client boundary.
- Capture is best-effort and isolated. It must never trigger provider retry, fallback, or turn failure.
- Session JSONL remains conversation memory. Pilot SQLite is not a context source.
- Use stdlib `sqlite3` behind `asyncio.to_thread`; do not add a database dependency for the pilot.
- Every task begins with a failing test, implements the smallest passing change, runs focused verification, then commits.
- Keep provider-specific routing and capture rules out of `AgentLoop` and `AgentRunner`.

## Delivery Order

| Workstream | Tasks | Depends on | Deployable checkpoint |
| --- | --- | --- | --- |
| A. Confidential pilot boundary | 1–5 | None | Closed WebUI/Telegram pilot with no visible reasoning |
| B. Routing and provider resilience | 6–9 | A contracts | Deterministic teacher routing and bounded failover |
| C. Consent-gated capture | 10–14 | Routing decision and turn ID | Isolated SQLite capture with privacy controls |
| D. Feedback, operations, and release gate | 15–19 | Pilot store and identity | Feedback loop, health, deletion, load and staging gate |

---

### Task 1: Add typed pilot configuration and secure defaults

**Files:**
- Modify: `nanobot/config/schema.py`
- Modify: `nanobot/channels/base.py`
- Modify: `tests/config/test_model_presets.py`
- Modify: `tests/channels/test_base_channel.py`
- Create: `tests/config/test_pilot_config.py`

- [ ] Write failing tests proving:
  - `ChannelsConfig().show_reasoning is False`;
  - pilot capture and future-training eligibility default to disabled;
  - routing rules reference existing model preset names;
  - a tool-heavy route rejects presets declared without tool support;
  - Gemini pilot candidates accept only the existing API-key configuration and no OAuth field;
  - retention values and queue limits reject zero/negative or unsafe values.

- [ ] Add these Pydantic contracts to `nanobot/config/schema.py`:

```python
class PilotModelClassConfig(Base):
    preset: str
    supports_tools: bool = True
    capture_policy: Literal["metrics_only", "answer", "reasoning"] = "metrics_only"
    input_cost_per_million: float | None = Field(default=None, ge=0)
    output_cost_per_million: float | None = Field(default=None, ge=0)

class PilotRoutingConfig(Base):
    enabled: bool = False
    policy_version: str = "pilot-routing-v1"
    default: PilotModelClassConfig
    reasoning: PilotModelClassConfig
    tool_heavy: PilotModelClassConfig
    fallbacks: list[str] = Field(default_factory=list)

class PilotCaptureConfig(Base):
    enabled: bool = False
    hmac_secret: str = Field(default="", repr=False)
    database_path: str = "~/.nanobot/pilot/events.db"
    queue_capacity: int = Field(default=1000, ge=10, le=100_000)
    flush_timeout_seconds: float = Field(default=5.0, gt=0, le=60)
    max_prompt_chars: int = Field(default=32_000, ge=1000)
    max_reasoning_chars: int = Field(default=64_000, ge=1000)
    max_answer_chars: int = Field(default=32_000, ge=1000)

class PilotRetentionConfig(Base):
    session_days: int = Field(default=30, ge=1)
    telemetry_days: int = Field(default=90, ge=1)
    raw_capture_days: int = Field(default=30, ge=1)
    training_eligible_days: int = Field(default=180, ge=1)

class PilotConfig(Base):
    enabled: bool = False
    routing: PilotRoutingConfig | None = None
    capture: PilotCaptureConfig = Field(default_factory=PilotCaptureConfig)
    retention: PilotRetentionConfig = Field(default_factory=PilotRetentionConfig)
    product_consent_version: str = "pilot-product-v1"
    training_consent_version: str = "pilot-training-v1"
```

- [ ] Add `pilot: PilotConfig` to top-level `Config`; validate preset references after `model_presets` is available, reject `tool_heavy.supports_tools=False`, and require a non-empty HMAC secret only when content capture is enabled.

- [ ] Change `ChannelsConfig.show_reasoning` and `BaseChannel.show_reasoning` defaults to `False`; update existing default assertions without weakening opt-in compatibility tests for non-pilot channels.

- [ ] Run:

```bash
uv run pytest tests/config/test_pilot_config.py tests/config/test_model_presets.py tests/channels/test_base_channel.py -q
uv run ruff check nanobot/config/schema.py nanobot/channels/base.py tests/config/test_pilot_config.py
```

- [ ] Commit:

```bash
git add nanobot/config/schema.py nanobot/channels/base.py tests/config/test_pilot_config.py tests/config/test_model_presets.py tests/channels/test_base_channel.py
git commit -m "feat(pilot): add secure pilot configuration"
```

### Task 2: Build the server-side presentation policy

**Files:**
- Create: `nanobot/pilot/__init__.py`
- Create: `nanobot/pilot/presentation.py`
- Create: `tests/pilot/test_presentation.py`
- Modify: `nanobot/channels/manager.py`
- Modify: `tests/channels/test_channel_manager_reasoning.py`
- Modify: `tests/channels/test_channel_manager_delta_coalescing.py`

- [ ] Write failing parameterized canary tests for `reasoning_content`, `thinking_blocks`, reasoning events, `<think>...</think>`, bearer/API-key/cookie strings, Windows and POSIX internal paths, tool arguments, and raw exception text. Cover streamed delta, stream end, and one-shot outbound delivery.

- [ ] Implement a pure, network-free policy:

```python
@dataclass(frozen=True, slots=True)
class PresentationResult:
    content: str
    metadata: dict[str, Any]
    blocked_fields: tuple[str, ...]
    leak_prevented: bool

class PresentationPolicy:
    """Pure outbound content/metadata sanitizer and event allow-policy."""
```

Implement `sanitize(content, metadata) -> PresentationResult` and `permits_event(event_type) -> bool`. The sanitizer must remove complete and unclosed `<think>` blocks, recursively drop reasoning/tool-argument/provider-error keys, redact secrets and internal paths, and return deterministic output.

- [ ] Inject one `PresentationPolicy` into `ChannelManager`; apply it in `_send_once` before every channel send. Drop reasoning event types when `show_reasoning=False`, and sanitize both content and copied metadata for ordinary messages/deltas.

- [ ] Add an in-memory counter callback to the policy so a blocked canary increments `presentation_leak_prevented_total` without logging the blocked value.

- [ ] Run:

```bash
uv run pytest tests/pilot/test_presentation.py tests/channels/test_channel_manager_reasoning.py tests/channels/test_channel_manager_delta_coalescing.py -q
uv run ruff check nanobot/pilot nanobot/channels/manager.py tests/pilot/test_presentation.py
```

- [ ] Commit:

```bash
git add nanobot/pilot nanobot/channels/manager.py tests/pilot tests/channels/test_channel_manager_reasoning.py tests/channels/test_channel_manager_delta_coalescing.py
git commit -m "feat(pilot): enforce outbound presentation policy"
```

### Task 3: Remove reasoning rendering from pilot clients

**Files:**
- Modify: `nanobot/channels/websocket/runtime.py`
- Modify: `nanobot/channels/telegram/runtime.py`
- Modify: `nanobot/webui/transcript.py`
- Modify: `webui/src/lib/types.ts`
- Modify: `webui/src/hooks/useNanobotStream.ts`
- Modify: `webui/src/components/MessageBubble.tsx`
- Modify: `webui/src/components/thread/AgentActivityCluster.tsx`
- Delete: `webui/src/components/thread/activity/reasoning-preview.ts`
- Delete: `webui/src/components/thread/activity/ReasoningRow.tsx`
- Delete: `webui/src/components/thread/activity/ThinkingReasoningShell.tsx`
- Modify: `webui/src/tests/useNanobotStream.test.tsx`
- Modify: `webui/src/tests/message-bubble.test.tsx`
- Modify: `webui/src/tests/agent-activity-cluster.test.tsx`
- Modify: `tests/utils/test_webui_transcript.py`
- Modify: `nanobot/channels/websocket/tests/test_websocket_channel.py`
- Create: `tests/pilot/test_reasoning_client_canaries.py`

- [x] Write failing WebUI tests that feed legacy `reasoning_delta`, `reasoning_end`, and `kind="reasoning"` frames and assert no message field or rendered DOM contains the canary. Keep a neutral pre-token “Đang xử lý…” state that contains no model text.

- [x] Make WebSocket and Telegram reasoning send methods no-op under the pilot policy, without including the reasoning value in logs or metadata.

- [x] Remove WebUI reasoning fields, transcript folding, reducers, activity-cluster branches, and visible components. Treat legacy reasoning frames as ignored compatibility input so stale servers and historical transcript records cannot expose content.

- [x] Search production client code for residual render paths:

```bash
rg -n "reasoning_delta|reasoning_end|reasoningStreaming|ReasoningBubble|thinking_blocks|reasoning_content" webui/src nanobot/channels/websocket nanobot/channels/telegram
```

Expected matches are limited to explicit ignore/no-op code and tests.

- [x] Run:

```bash
cd webui && bun run test -- useNanobotStream message-bubble
cd .. && uv run pytest tests/pilot/test_reasoning_client_canaries.py nanobot/channels/telegram/tests/test_telegram_channel.py -q
```

- [x] Commit:

```bash
git add -A nanobot/channels/websocket nanobot/channels/telegram nanobot/webui/transcript.py webui/src tests/utils/test_webui_transcript.py tests/pilot/test_reasoning_client_canaries.py
git commit -m "feat(pilot): remove client reasoning surfaces"
```

### Task 4: Lock WebUI and Telegram ingress before side effects

**Files:**
- Modify: `nanobot/channels/websocket/runtime.py`
- Modify: `nanobot/channels/telegram/runtime.py`
- Modify: `nanobot/channels/manager.py`
- Modify: `nanobot/channels/telegram/manifest.py`
- Modify: `nanobot/channels/telegram/webui/locales/en.json`
- Modify: `nanobot/channels/telegram/webui/locales/vi.json`
- Modify: `nanobot/channels/telegram/tests/test_telegram_channel.py`
- Modify: `tests/webui/test_ingress_policy.py`
- Modify: `tests/channels/test_channel_plugins.py`

- [x] Add failing tests proving unauthorized WebSocket and Telegram senders receive an access/pairing response before attachment storage, media download, transcript write, bus publish, or teacher call.

- [x] Extend `TelegramConfig.group_policy` to `Literal["disabled", "mention", "allowlist"]` with default `"disabled"`. The current value is `Literal["open", "mention"]` default `"mention"` (`nanobot/channels/telegram/runtime.py`), so this is a **breaking change**: it removes `"open"` and flips the default. To avoid bricking existing configs, keep `"open"` accepted as a deprecated alias mapped to `"allowlist"` (log a one-time deprecation warning) for one release, then remove it. Define semantics:
  - `disabled`: ignore group updates;
  - `mention`: require the chat ID in a new `group_allow_from` list, an allowed sender, and a direct bot mention;
  - `allowlist`: require the chat ID in `group_allow_from` and an allowed sender, then accept messages without mention.
  Update existing `test_telegram_channel.py` assertions that assume `default == "mention"` or the `"open"` literal.

- [x] Keep Telegram DM pairing behavior. Re-check authorization immediately before `_handle_message`, as WebSocket already does after async hydration.

- [x] Have `ChannelManager` pass top-level pilot mode into WebSocket construction. Require WebSocket token authentication when pilot mode is enabled, reject wildcard `allow_from=["*"]` in pilot mode, and keep the existing short-lived token flow as the invite mechanism. Do not add registration endpoints.

- [x] Run:

```bash
uv run pytest nanobot/channels/telegram/tests/test_telegram_channel.py tests/webui/test_ingress_policy.py tests/channels/test_channel_validation.py -q
```

- [ ] Commit:

```bash
git add nanobot/channels/websocket/runtime.py nanobot/channels/telegram nanobot/channels/manager.py tests/webui/test_ingress_policy.py tests/channels/test_channel_validation.py tests/channels/test_channel_plugins.py
git commit -m "feat(pilot): enforce invite-only channel ingress"
```

### Task 5: Introduce compact stable turn identity

**Files:**
- Create: `nanobot/pilot/turns.py`
- Create: `tests/pilot/test_turn_ids.py`
- Modify: `nanobot/agent/loop.py`
- Modify: `nanobot/agent/turn_delivery.py`
- Modify: `nanobot/session/manager.py`
- Modify: `nanobot/bus/events.py`
- Modify: `nanobot/channels/websocket/runtime.py`
- Modify: `nanobot/channels/telegram/runtime.py`
- Modify: `webui/src/lib/types.ts`

- [x] Write failing tests for uniqueness across 20 concurrent turns, stable propagation to final outbound metadata, WebSocket completion frames, and Telegram send metadata. Assert IDs fit Telegram callback data when prefixed with `fb:x:`.

- [x] Implement `new_turn_id() -> str` as lowercase UUID4 hex and replace **both** current ID sites: `f"{key}:{time.time_ns()}"` in `AgentLoop` (`nanobot/agent/loop.py`, turn creation) and the stream base id `f"{self.session_key}:{time.time_ns()}"` in `nanobot/agent/turn_delivery.py`; never encode channel, chat, or user identifiers in a turn ID.

- [x] Add the accepted `turn_id` to `TurnContext.attributes`, `RequestContext`, `OutboundMessage.metadata`, WebSocket final frames, and Telegram message bookkeeping. Persist `_pilot_turn_id` only on the internal assistant session record and add a scoped `SessionManager` lookup for the preceding user message; strip the private key from WebUI hydration and provider request payloads. Preserve the WebUI client request ID separately as `client_turn_id`.

- [x] Run:

```bash
uv run pytest tests/pilot/test_turn_ids.py tests/agent/test_turn_delivery.py tests/webui/test_gateway_webui_smoke.py -q
```

- [ ] Commit:

```bash
git add nanobot/pilot/turns.py tests/pilot/test_turn_ids.py nanobot/agent/loop.py nanobot/agent/turn_delivery.py nanobot/session/manager.py nanobot/bus/events.py nanobot/channels/websocket/runtime.py nanobot/channels/telegram/runtime.py webui/src/lib/types.ts
git commit -m "feat(pilot): propagate stable turn identifiers"
```

---

### Task 6: Implement deterministic routing decisions

**Files:**
- Create: `nanobot/pilot/routing.py`
- Create: `tests/pilot/test_routing.py`
- Modify: `nanobot/agent/loop.py`
- Modify: `tests/agent/test_model_runtime_resolver.py`

- [x] Write table-driven failing tests for general, math/logic, code, explicit multi-step, tool-heavy, image/file, and long-input cases. Repeat each case to prove identical input/config/health yields identical output.

- [x] Implement these immutable contracts:

```python
RouteClass = Literal["default", "reasoning", "tool_heavy"]

@dataclass(frozen=True, slots=True)
class RoutingInput:
    channel: str
    content: str
    media_types: tuple[str, ...]
    available_tools: tuple[str, ...]

@dataclass(frozen=True, slots=True)
class RoutingDecision:
    turn_id: str
    route_class: RouteClass
    primary_preset: str
    fallback_presets: tuple[str, ...]
    reason_code: str
    policy_version: str
```

- [x] Classify using normalized text length, deterministic keyword/shape rules, media types, and non-empty tool definitions. The `reason_code` must be a fixed enum-like code, never user content.

- [x] In `AgentLoop._build_turn`, after session restoration and before context construction, call the router for user turns, resolve the selected preset through `ModelRuntimeResolver.resolve_preset`, assign `ctx.runtime`, and serialize the decision into `ctx.attributes["routing_decision"]`. System, Dream, explicit SDK runtime overrides, and command-only turns bypass pilot routing.

- [x] Run:

```bash
uv run pytest tests/pilot/test_routing.py tests/agent/test_model_runtime_resolver.py tests/agent/test_loop_runner_integration.py -q
```

- [ ] Commit:

```bash
git add nanobot/pilot/routing.py tests/pilot/test_routing.py nanobot/agent/loop.py tests/agent/test_model_runtime_resolver.py
git commit -m "feat(pilot): route turns deterministically"
```

### Task 7: Record provider attempts and harden retry classification

**Files:**
- Modify: `nanobot/providers/base.py`
- Modify: `nanobot/providers/fallback_provider.py`
- Modify: `nanobot/providers/factory.py`
- Modify: `nanobot/agent/hook.py`
- Modify: `nanobot/agent/runner.py`
- Create: `tests/pilot/test_provider_attempts.py`
- Modify: `tests/providers/test_provider_retry.py`
- Modify: `tests/agent/test_runner_fallback.py`

- [x] Write failing tests proving every primary/retry/fallback call produces one content-free `ProviderAttempt`, while authentication, invalid-request, policy/refusal, and context-length failures are not retried.

- [x] Add:

```python
@dataclass(frozen=True, slots=True)
class ProviderAttempt:
    provider: str
    model: str
    sequence: int
    retry_index: int
    fallback_index: int | None
    latency_ms: int
    finish_reason: str
    error_class: str | None
    usage: dict[str, int]
```

Store attempts on `LLMResponse.attempts`. Give every provider instance a non-secret configured provider alias in the factory, compose attempt lists in the base retry loop and `FallbackProvider`, and never put raw error content in an attempt.

- [x] Add `on_provider_attempt(context, attempt)` to `AgentHook`/`CompositeHook`. Attempts are **composed at the call site, not by the runner**: the base provider retry loop (`LLMProvider._run_with_retry`) and `FallbackProvider` append one content-free `ProviderAttempt` per provider call onto `LLMResponse.attempts` as each call completes. The hook then reads `context.response.attempts` (per-iteration, in `AgentHookContext`) to observe them; `AgentRunner` does not fabricate attempts itself. Emit so the hook observes response attempts before tool execution or finalization of that iteration.

- [x] Replace text-first retry/fallback decisions with structured status/kind/type/code precedence. Keep legacy text matching only when structured metadata is absent.

- [x] Run:

```bash
uv run pytest tests/pilot/test_provider_attempts.py tests/providers/test_provider_retry.py tests/agent/test_runner_fallback.py -q
```

- [x] Commit:

```bash
git add nanobot/providers/base.py nanobot/providers/fallback_provider.py nanobot/providers/factory.py nanobot/agent/hook.py nanobot/agent/runner.py tests/pilot/test_provider_attempts.py tests/providers/test_provider_retry.py tests/agent/test_runner_fallback.py
git commit -m "feat(pilot): expose sanitized provider attempts"
```

### Task 8: Make circuit state provider/model scoped

**Files:**
- Create: `nanobot/pilot/circuit.py`
- Create: `tests/pilot/test_circuit.py`
- Modify: `nanobot/providers/fallback_provider.py`
- Modify: `nanobot/pilot/routing.py`

- [ ] Write failing fake-clock tests for closed → open → half-open → closed transitions, isolation by `(provider, model)`, authentication immediate-open behavior, transient failure threshold, cooldown, and single half-open probe.

- [ ] Implement a process-level `CircuitRegistry` with an `asyncio.Lock`, injected monotonic clock, snapshot API, and no prompt/user data.

- [ ] Make routing filter open candidates before producing `RoutingDecision`. Make `FallbackProvider` update the same registry after each attempt. Do not use the existing wrapper-global `_primary_failures` as the authority.

- [ ] Verify an open primary is skipped, an open fallback is omitted, and all-open candidates yield one sanitized terminal error with no provider details.

- [ ] Run:

```bash
uv run pytest tests/pilot/test_circuit.py tests/pilot/test_routing.py tests/agent/test_runner_fallback.py -q
```

- [ ] Commit:

```bash
git add nanobot/pilot/circuit.py nanobot/pilot/routing.py nanobot/providers/fallback_provider.py tests/pilot/test_circuit.py tests/pilot/test_routing.py tests/agent/test_runner_fallback.py
git commit -m "feat(pilot): add model-scoped circuit breaking"
```

### Task 9: Verify one-answer fallback semantics

**Files:**
- Modify: `nanobot/providers/fallback_provider.py`
- Modify: `nanobot/agent/turn_delivery.py`
- Create: `tests/pilot/test_fallback_delivery.py`

- [ ] Add integration tests for primary failure before streaming, timeout after a partial stream, non-timeout failure after content, exhausted fallback, and capture-hook exception. Count client-visible final messages and assert exactly one.

- [ ] Preserve the current stream recovery segment mechanism, but buffer a fallback candidate until it produces an accepted segment boundary. Sanitize the exhausted error through `PresentationPolicy`.

- [ ] Assert capture-hook failure does not alter retry/fallback counters and does not create another provider attempt.

- [ ] Run:

```bash
uv run pytest tests/pilot/test_fallback_delivery.py tests/agent/test_runner_fallback.py tests/agent/test_turn_delivery.py -q
```

- [ ] Commit:

```bash
git add nanobot/providers/fallback_provider.py nanobot/agent/turn_delivery.py tests/pilot/test_fallback_delivery.py
git commit -m "fix(pilot): guarantee single-answer failover"
```

---

### Task 10: Implement HMAC identity, redaction, and capture gates

**Files:**
- Create: `nanobot/pilot/identity.py`
- Create: `nanobot/pilot/redaction.py`
- Create: `nanobot/pilot/consent.py`
- Create: `nanobot/pilot/types.py`
- Create: `tests/pilot/test_identity.py`
- Create: `tests/pilot/test_redaction.py`
- Create: `tests/pilot/test_consent.py`

- [ ] Write failing tests for deterministic domain-separated HMAC user/session IDs, secret rotation versioning, raw Telegram/WebSocket identity absence, API keys, bearer tokens, cookies, private-key markers, Windows/POSIX paths, size bounds, stale consent, and all operator/user/provider gate combinations.

- [ ] Implement `IdentityHasher` with `HMAC-SHA256(secret, f"{version}:{domain}:{value}")`; return hex digests and never retain the source value.

- [ ] Implement recursive `Redactor` for strings, mappings, and sequences. Return both redacted data and a set of rule codes; never return matched secret text in diagnostics.

- [ ] Implement:

```python
@dataclass(frozen=True, slots=True)
class ConsentState:
    product_allowed: bool = False
    training_allowed: bool = False
    product_version: str = ""
    training_version: str = ""
    updated_at_ms: int = 0

@dataclass(frozen=True, slots=True)
class CaptureDecision:
    store_prompt: bool
    store_reasoning: bool
    store_answer: bool
    training_eligible: bool
    policy_version: str
```

Future-training consent must default false and never imply product consent. Missing/stale consent produces metrics-only capture.

- [ ] Run:

```bash
uv run pytest tests/pilot/test_identity.py tests/pilot/test_redaction.py tests/pilot/test_consent.py -q
```

- [ ] Commit:

```bash
git add nanobot/pilot/identity.py nanobot/pilot/redaction.py nanobot/pilot/consent.py nanobot/pilot/types.py tests/pilot
git commit -m "feat(pilot): add capture privacy primitives"
```

### Task 11: Build the prioritized bounded capture queue

**Files:**
- Create: `nanobot/pilot/queue.py`
- Create: `tests/pilot/test_capture_queue.py`

- [ ] Write failing async tests for capacity, FIFO within priority, verbose-reasoning eviction, preservation of consent/feedback/final outcome/attempt metadata, depth/drop counters, blocked consumer wakeup, and bounded shutdown drain.

- [ ] Implement `CapturePriority` ordered as `CONSENT`, `FEEDBACK`, `FINAL`, `ATTEMPT`, `ARTIFACT`. Use an `asyncio.Condition` and a bounded heap/deque structure so a higher-priority event can evict the oldest lower-priority event when full.

- [ ] Expose content-free `QueueSnapshot(capacity, depth, dropped_by_kind, accepted_total)`.

- [ ] Run:

```bash
uv run pytest tests/pilot/test_capture_queue.py -q
```

- [ ] Commit:

```bash
git add nanobot/pilot/queue.py tests/pilot/test_capture_queue.py
git commit -m "feat(pilot): add prioritized capture queue"
```

### Task 12: Create the versioned SQLite WAL event store

**Files:**
- Create: `nanobot/pilot/migrations.py`
- Create: `nanobot/pilot/store.py`
- Create: `tests/pilot/test_store_migrations.py`
- Create: `tests/pilot/test_event_store.py`

- [ ] Write failing tests for migration from an empty database, `PRAGMA journal_mode=WAL`, foreign keys, all six logical entities, append-only feedback, idempotent event IDs across reopen, database size, last successful write, and rollback on batch failure.

- [ ] Migration 1 creates `schema_migrations`, `turns`, `attempts`, `artifacts`, `feedback`, `consents`, and `deletions`. Use opaque event IDs as primary keys, pseudonymous IDs only, UTC integer milliseconds, and JSON text only for bounded sanitized structures.

- [ ] Implement synchronous transaction methods inside `SQLitePilotStore`; call them only through `asyncio.to_thread` from the single writer. No store method may return artifacts for model-context construction.

- [ ] Add ownership lookup `(turn_id, user_pseudonym, session_pseudonym)`, consent lookup, aggregate metrics queries, deletion-by-pseudonym transaction, and dry-run retention counts.

- [ ] Run:

```bash
uv run pytest tests/pilot/test_store_migrations.py tests/pilot/test_event_store.py -q
```

- [ ] Commit:

```bash
git add nanobot/pilot/migrations.py nanobot/pilot/store.py tests/pilot/test_store_migrations.py tests/pilot/test_event_store.py
git commit -m "feat(pilot): add sqlite event store"
```

### Task 13: Add the isolated distillation capture hook and service lifecycle

**Files:**
- Create: `nanobot/pilot/capture.py`
- Create: `nanobot/pilot/service.py`
- Create: `nanobot/pilot/metrics.py`
- Create: `tests/pilot/test_capture_hook.py`
- Create: `tests/pilot/test_pilot_service.py`
- Modify: `nanobot/agent/hook.py`
- Modify: `nanobot/cli/commands.py`

- [ ] Write failing tests showing the hook observes routing, approved prompt/context, provider/model generation settings, reasoning shapes, final answer, sanitized tool trajectory, attempts, usage, latency, and stop reason; assert it has no bus/channel reference and cannot publish outbound messages.

- [ ] Implement `DistillationCaptureHook(AgentHook)` from `AgentTurnHookContext`. Accumulate per-iteration data, apply `CaptureDecision` and `Redactor`, then enqueue immutable events in `after_run`/`on_error`. Catch errors at the hook boundary and increment content-free failure metrics.

- [ ] Implement `PilotService.start()`, `hook_factory()`, `health_snapshot()`, and `stop()`. The writer consumes batches sequentially and calls `SQLitePilotStore.write_batch` through `asyncio.to_thread`. Startup migration/writer failure marks capture degraded but returns a usable service whose hook stores metrics only.

- [ ] In gateway construction (`nanobot/cli/commands.py`), create one service and wire it at the exact bootstrap points: append `pilot_service.hook_factory` to the `hook_factories=[...]` list at the gateway `AgentLoop.from_config(...)` call (the `gateway` command's agent construction, ~line 1923, alongside `create_file_edit_activity_hook`); call `pilot_service.start()` before `channels.start_all()` (~line 2333, i.e. before the `nanobot-channels` task is created); and call `pilot_service.stop()` in the shutdown `finally` block after `await channels.stop_all()` (~line 2384) so channels stop accepting ingress first, but before loop shutdown completes. Respect configured flush timeout and report unpersisted count without logging content. Note: the gateway runs as a child process (`nanobot/gateway/runtime.py:build_gateway_command`); these anchors are inside that child's entrypoint, so no separate gateway file needs editing.

- [ ] Measure enqueue-path duration in tests with a deliberately slow writer and assert the hook does not wait for persistence.

- [ ] Run:

```bash
uv run pytest tests/pilot/test_capture_hook.py tests/pilot/test_pilot_service.py tests/agent/test_hook_composite.py -q
```

- [ ] Commit:

```bash
git add nanobot/pilot/capture.py nanobot/pilot/service.py nanobot/pilot/metrics.py tests/pilot nanobot/agent/hook.py nanobot/cli/commands.py
git commit -m "feat(pilot): wire isolated capture service"
```

### Task 14: Add consent commands, revocation, deletion, and retention

**Files:**
- Modify: `nanobot/command/builtin.py`
- Create: `nanobot/pilot/retention.py`
- Create: `tests/pilot/test_privacy_commands.py`
- Create: `tests/pilot/test_retention.py`
- Modify: `nanobot/session/manager.py`
- Modify: `nanobot/webui/ws_http.py`

- [ ] Write failing tests for `/consent status`, `/consent product on|off`, `/consent training on|off`, and `/privacy delete`. Verify separate versioned states, training default-off, revocation removing eligibility, and authorization scoped to the current sender/session.

- [ ] Persist consent events at highest queue priority and maintain a small authoritative consent table via the writer. A stale version is denied until the user explicitly accepts the current version.

- [ ] Implement deletion orchestration that first blocks new capture for the pseudonym, deletes session JSONL through `SessionManager`, deletes artifacts/turns/feedback/consents transactionally, and appends a content-free deletion audit. Repeating deletion is an idempotent success.

- [ ] Extend existing WebUI session deletion to invoke the same pilot deletion service. Add `RetentionService.plan(now)` and `apply(plan)` so dry-run/report and apply share the exact candidate IDs; exclude in-flight turn IDs supplied by `AgentLoop`.

- [ ] Run:

```bash
uv run pytest tests/pilot/test_privacy_commands.py tests/pilot/test_retention.py tests/agent/test_session_delete.py tests/webui/test_session_list_index.py -q
```

- [ ] Commit:

```bash
git add nanobot/command/builtin.py nanobot/pilot/retention.py tests/pilot nanobot/session/manager.py nanobot/webui/ws_http.py
git commit -m "feat(pilot): add consent deletion and retention"
```

---

### Task 15: Add transport-neutral feedback handling

**Files:**
- Create: `nanobot/pilot/feedback.py`
- Create: `tests/pilot/test_feedback.py`
- Modify: `nanobot/bus/events.py`
- Modify: `nanobot/bus/queue.py`
- Modify: `nanobot/agent/loop.py`

- [ ] Write failing tests for `helpful`, `incorrect`, `retry`, and `explain_more`; action-ID idempotency; ownership denial; immutable original answers; and `retry_of`/`explanation_of` links.

- [ ] Add `FeedbackAction` and `FeedbackAck` typed bus events. `FeedbackService.handle` must:
  1. HMAC the channel identity;
  2. verify turn ownership in SQLite;
  3. append feedback idempotently;
  4. return an acknowledgement;
  5. for retry/explain, publish a new `InboundMessage` only after authorization succeeds.

- [ ] Reconstruct retry input from the authorized session history by the internal `_pilot_turn_id`, not capture artifacts. For `explain_more`, create a fixed user-facing explanation request and strip `reasoning_content`/`thinking_blocks` from the replay context before invoking the model.

- [ ] Ensure feedback works when content capture is disabled because operational `turns` ownership rows are content-free and always retained for the configured telemetry window.

- [ ] Run:

```bash
uv run pytest tests/pilot/test_feedback.py tests/bus/test_outbound_events.py tests/session/test_turn_continuation.py -q
```

- [ ] Commit:

```bash
git add nanobot/pilot/feedback.py tests/pilot/test_feedback.py nanobot/bus/events.py nanobot/bus/queue.py nanobot/agent/loop.py
git commit -m "feat(pilot): add scoped feedback workflow"
```

### Task 16: Expose feedback in WebUI and Telegram

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

- [ ] Write failing client tests for all four actions, stable `turn_id`, generated action IDs, disabled double-click, success/error acknowledgement, and P95-independent local optimistic state.

- [ ] Add WebSocket envelope `type="feedback"` and response event `feedback_ack`. Route it to `FeedbackService` without creating an agent turn for helpful/incorrect.

- [ ] Add a Telegram inline keyboard to each accepted final answer using callback data `fb:<action-code>:<turn-id>`. Ignore/reject callbacks from another user before feedback persistence. Edit or answer the callback with a short acknowledgement; do not echo stored content.

- [ ] Render four accessible WebUI actions beneath completed assistant messages. Hide them for streaming, command/system, and legacy messages without a turn ID.

- [ ] Run:

```bash
cd webui && bun run test -- assistant-feedback-actions message-bubble nanobot-client useNanobotStream
cd .. && uv run pytest nanobot/channels/telegram/tests/test_telegram_channel.py tests/pilot/test_feedback.py -q
```

- [ ] Commit:

```bash
git add nanobot/channels/websocket/runtime.py nanobot/channels/telegram/runtime.py nanobot/channels/telegram/tests/test_telegram_channel.py webui/src tests/pilot/test_feedback.py
git commit -m "feat(pilot): add webui and telegram feedback"
```

### Task 17: Add sensitive-safe health and operational metrics

**Files:**
- Modify: `nanobot/pilot/metrics.py`
- Create: `nanobot/pilot/health.py`
- Create: `nanobot/webui/pilot_api.py`
- Create: `tests/pilot/test_metrics.py`
- Create: `tests/webui/test_pilot_api.py`
- Modify: `nanobot/webui/ws_http.py`
- Modify: `nanobot/webui/gateway_services.py`

- [ ] Write failing tests for success/error, TTFT/total latency, provider/model latency, retry/fallback/circuit, usage/estimated cost, feedback, queue depth/drops/writer failures, active WebUI/Telegram users, D1/D7 return, retention, DB size, and last write.

- [ ] Implement bounded-label counters and fixed-bucket histograms. Allowed labels are channel, configured provider/model alias, route class, status/error class, and policy version. Reject labels containing prompts, answers, reasoning, credentials, turn/session/user IDs, or arbitrary provider error text.

- [ ] Add authenticated `GET /api/pilot/health` and `GET /api/pilot/metrics` routes. Health has separate `agent`, `providers`, `channels`, and `capture_store` sections with `ok|degraded|down`; metrics returns JSON snapshots for the operator UI/collector.

- [ ] Compute D1/D7 and feedback distribution from aggregate SQL queries, never from metric labels containing identity.

- [ ] Run:

```bash
uv run pytest tests/pilot/test_metrics.py tests/webui/test_pilot_api.py tests/webui/test_settings_routes.py -q
```

- [ ] Commit:

```bash
git add nanobot/pilot/metrics.py nanobot/pilot/health.py nanobot/webui/pilot_api.py tests/pilot/test_metrics.py tests/webui/test_pilot_api.py nanobot/webui/ws_http.py nanobot/webui/gateway_services.py
git commit -m "feat(pilot): expose safe health and metrics"
```

### Task 18: Add concurrency, performance, and leak regression gates

**Files:**
- Create: `tests/pilot/test_concurrent_turns.py`
- Create: `tests/pilot/test_capture_performance.py`
- Create: `tests/pilot/test_feedback_performance.py`
- Create: `tests/pilot/test_reasoning_leak_regression.py`
- Modify: `.github/workflows/ci.yml`

- [ ] Build a deterministic fake teacher that emits unique per-turn answer/reasoning canaries, tool calls, retries, and fallback outcomes. Run 20 active WebUI/Telegram turns and assert no session, stream, turn ID, reasoning, or feedback ownership mixing.

- [ ] Benchmark capture hook enqueue with a slow writer for enough iterations to calculate P95; assert added response-path latency ≤50 ms. Benchmark local feedback handling and assert P95 acknowledgement ≤1 s, excluding mocked channel transport.

- [ ] Capture logs, outbound payloads, WebSocket frames, Telegram calls, exception responses, and metric snapshots; assert every reasoning canary is absent.

- [ ] Add a dedicated CI job for pilot tests and WebUI leak tests. Keep performance thresholds on a deterministic fake clock where possible; mark only the wall-clock envelope tests with a documented generous timeout.

- [ ] Run:

```bash
uv run pytest tests/pilot -q
uv run pytest tests/pilot/test_concurrent_turns.py -q
cd webui && bun run test
```

- [ ] Commit:

```bash
git add tests/pilot .github/workflows/ci.yml
git commit -m "test(pilot): gate concurrency performance and privacy"
```

### Task 19: Complete release verification and operator runbooks

**Files:**
- Create: `docs/pilot/configuration.md`
- Create: `docs/pilot/privacy-operations.md`
- Create: `docs/pilot/provider-failover.md`
- Create: `docs/pilot/staging-checklist.md`
- Create: `scripts/pilot_smoke.py`
- Create: `tests/pilot/test_smoke_script.py`

- [ ] Document a complete configuration example using DeepSeek, Qwen/DashScope, Gemini API key, explicit fallback presets, finite WebUI/Telegram allowlists, reasoning disabled, capture gates, independent retention, cost ceiling, and alert thresholds. Use environment-variable placeholders, never usable credentials.

- [ ] Document user consent/revocation/deletion, API-key rotation, capture disablement, SQLite backup/restore (including WAL checkpoint), retention dry-run/apply, provider shutdown, channel shutdown, and incident response for a reasoning leak.

- [ ] Implement a read-only-by-default smoke script. `--fault-injection` uses configured fake endpoints only and verifies retry/fallback/circuit. `--backup-restore <temporary-directory>` verifies store restoration without touching the live database.

- [ ] Run the complete local gate:

```bash
uv sync --all-extras --dev
uv run --no-sync python -m scripts.install_channel_dependencies --all-channels
uv run --no-sync ruff check nanobot tests scripts
uv run --no-sync basedpyright
uv run --no-sync pytest -q
cd webui && bun run test && bun run build
```

- [ ] Review acceptance traceability below and record evidence links/results in `docs/pilot/staging-checklist.md`.

- [ ] Commit:

```bash
git add docs/pilot scripts/pilot_smoke.py tests/pilot/test_smoke_script.py
git commit -m "docs(pilot): add release and operations gate"
```

## Acceptance Traceability

| Approved criterion group | Primary tasks | Required evidence |
| --- | --- | --- |
| Access and channels | 1, 4, 5 | Unauthorized-side-effect tests; DM/media/group tests; session isolation |
| Reasoning confidentiality | 1–3, 18 | Canary unit/integration tests across payloads, logs, errors, metrics |
| Routing and provider execution | 6–9 | Determinism tables; structured retry tests; circuit fake-clock tests; one-answer integration |
| Feedback | 5, 15, 16 | Ownership/idempotency/link tests on WebUI and Telegram |
| Consent and privacy | 10, 13, 14 | Gate matrix; HMAC/redaction tests; revocation/deletion integration |
| Queue and store | 11–13 | Priority pressure tests; WAL/migration/restart tests; capture isolation |
| Retention and observability | 14, 17 | Dry-run/apply equivalence; safe-label tests; health snapshots |
| Performance | 13, 16, 18 | Capture P95, feedback P95, slow-writer and 20-turn concurrency evidence |
| Required verification | 18, 19 | Full Python/WebUI/type/lint/build results and staging checklist |

## Pilot Exit Gate (Operational, Not a Code Commit)

- [ ] All tasks 1–19 are merged and the full verification command is green.
- [ ] Security/privacy review has no unresolved high-severity issue.
- [ ] Privacy notice and Vietnamese/English consent text are approved by the operator.
- [ ] Finite invite/allowlists and a named pilot-support owner are recorded.
- [ ] Daily provider cost ceiling and alert are active.
- [ ] Fault injection demonstrates retry, fallback, circuit open/cooldown, and one-answer delivery.
- [ ] SQLite backup and restore complete successfully against a staging copy.
- [ ] Staging runs continuously for 72 hours with no reasoning canary leak, task/process leak, or capture-caused chat outage.
- [ ] D1/D7 retention, answer success rate, latency, feedback, provider cost, queue drops, and writer health are reviewed before admitting pilot users.

## Deferred Follow-on Plans

Create separate design/implementation plans only after this exit gate for:

1. unofficial `openzalo`/Zalo Personal channel isolation and account-risk controls;
2. governed dataset review/export and sample quality scoring;
3. SLM distillation and self-hosted inference;
4. public signup, quotas, and billing;
5. operator-owned Gemini OAuth experiments.

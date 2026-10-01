# Coworker extension (fork-only)

Features ported from **AICoworker** (an OpenClaw-based desktop agent) into nanobot as a
self-contained module, `nanobot/coworker/`, so the fork can keep merging upstream
nanobot while retaining them.

| # | Feature | AICoworker source it mirrors | nanobot module |
|---|---------|------------------------------|----------------|
| 1a | **Advisor** — a stronger model reviews the executor's live session | `gateway/advisor-consult.ts`, `tools/advisor.cjs`, `directives/advisor.cjs`, `[auto-advisor-review]` nudge in `run/attempt.ts` | `coworker/advisor/` |
| 1b | **Delegate in a room** — named teammates with their own model preset | `gateway/room/room-turns.ts`, `room-delegate-bridge.ts`, `tools/room-delegate.cjs` | `coworker/room/scheduler.py`, `room/tools.py` |
| 1c | **Room state** — shared key/value scratchpad per room | `tools/room-state.cjs`, `lib/room-state-store.cjs` | `coworker/room/store.py`, `room/tools.py` |
| 2a | **Token cache optimization** — cache-aware prefix changes, system-prompt freeze, keep-alive pings | `lib/context-inspector.cjs` (idle gate), `system-prompt-freeze.ts`, `cache-keepalive*.ts` | `coworker/context/optimizer.py`, `context/keepalive.py` |
| 2b | **Trim context** — block-aligned history trim, junk prune, `mark_context_wasted` | `ctxComputeAutoTrim`, `ctxClassifyJunk`, `tools/mark-context-wasted.cjs` | `coworker/context/optimizer.py`, `context/tools.py` |
| 3a | **Save as workflow** — distill a session into a draft step-graph | `agents/workflows/distill.ts`, `tools/workflow-distill.cjs` | `coworker/workflows/distill.py` |
| 3b | **Run workflows** — deterministic engine, harness drives one step per turn | `agents/workflows/{format,engine}.ts`, `pi-extensions/workflow-continuation.ts` | `coworker/workflows/{format,engine,registry,drive}.py` |

Workflow bundles are file-compatible with AICoworker (`workflow.md` + `steps/*.md`,
wikilink edges, `## Next`, `## Output` JSON-Schema).

## How it plugs in (merge-safety design)

All logic lives in files upstream never touches. The core is reached through **five
small seams**; each is generic (not coworker-specific) and guarded by
`tests/coworker/test_seams.py`, so a merge that drops one fails CI loudly.

| Seam | Upstream file | Change |
|------|---------------|--------|
| S1 | `nanobot/agent/hook.py` | `AgentHook.transform_request(context, messages, tools, *, stateful)` (+ pipeline in `CompositeHook`). Reshapes one outgoing payload without touching the transcript. |
| S2 | `nanobot/agent/runner.py` | `_request_model` calls `hook.transform_request(...)` after `context_governor.prepare_request`. |
| S3 | `nanobot/agent/turn_hooks.py` | Turn hook chain appends `extension_hook_factories()`. |
| S4 | `nanobot/command/builtin.py` | `register_builtin_commands` ends with `register_extension_commands(router)`. |
| S5 | `nanobot/agent/tools/coworker.py` (new file) | Import shim so the existing pkgutil scan registers coworker tools. |

`nanobot/agent/extensions.py` (new file) discovers extensions: the built-in
`nanobot.coworker` plus anything registered under the `nanobot.extensions` entry-point
group. An extension module exposes `hook_factories()` and/or `register_commands(router)`.

Runtime services (bus, sessions, subagents, preset loader) are captured from the
`ToolContext` when the first coworker tool is created — no constructor changes in
`AgentLoop`.

### Merging upstream

1. `git merge origin/main` (or the upstream remote). Conflicts, if any, can only be in
   the S1–S4 files; each seam is a few lines — re-apply them as in the table above.
2. `uv run --no-sync pytest tests/coworker -q` — seam guards + feature tests.
3. `uv run --no-sync basedpyright` and `ruff check nanobot/` as usual.

Seams S1 and S3/S4 are upstreamable as-is ("request transform hook", "extension
discovery"); if upstream accepts them, the fork diff shrinks to new files only.

## Configuration

`~/.nanobot/coworker.json` (next to `config.json`; override with
`NANOBOT_COWORKER_CONFIG`). Re-read on change — no restart needed. Every feature is
off or inert by default, so an unconfigured install behaves exactly like upstream
(plus the two workflow tools).

```json
{
  "advisor": {
    "preset": "opus",
    "maxUses": 10,
    "maxTokens": 4096,
    "timeoutSeconds": 180,
    "reviewNudge": true,
    "firstConsultGap": 2,
    "reconsultGap": 12,
    "discussionGate": "brainstorm",
    "discussionMinChars": 800,
    "stuckDetection": true
  },
  "room": {
    "agents": [
      {"id": "researcher", "name": "Researcher", "emoji": "🔎", "bio": "Web research, fact-checking, sources",
       "preset": "fast", "instructions": "Cite every source URL."},
      {"id": "writer", "name": "Writer", "emoji": "✍️", "bio": "Vietnamese marketing copy",
       "preset": null}
    ],
    "maxChainedTurns": 16,
    "guestTimeoutSeconds": 900
  },
  "context": {
    "trim": {"enabled": true, "maxTurns": 20},
    "optimize": true,
    "freezeSystemPrompt": false,
    "freezeMaxHoldMinutes": 60,
    "cacheTtlSeconds": null,
    "keepalive": {"enabled": false, "strategy": "ping", "windowMinutes": 30, "maxPings": 4, "leadSeconds": 60}
  },
  "workflows": {"enabled": true, "stepMaxRetries": 3, "maxStepTurns": 100}
}
```

`preset` values are model preset names from `config.json` (`modelPresets`, or `default`).

## Feature notes

### Advisor
- Tool `advisor(focus?)` is visible only when a preset is configured (globally, or per session with the
  **Advisor** switch in the chat header / `/advisor on [preset]`; `/advisor off`, `/advisor default`).
  The switch is manual and per session: it overrides the global setting in both directions.
- Two modes, chosen in the same popover or with `/advisor brainstorm` / `/advisor code`:
  - **coding** (default): orient, consult before the first write, consult again before finishing;
    thin-context refusal, stuck detection, and the review nudge apply.
  - **brainstorm**: for discussion and decisions. The agent consults before it recommends anything,
    with no "read files first" phase (no thin-context refusal), under a thinking-partner reviewer prompt
    that argues for a position instead of reviewing work. Discussion gate applies when drafts are long.
- Every successful consult is kept (last 6, `focus` + advice, cleared by `/new`) and shown as **Advisor Q&A**
  in the header popover and the inspector, so you can see what the agent asked and what it was told.
- The consult forwards the executor's **live** message list (system prompt + history +
  current run, captured by the hook) as quoted data under a clean reviewer system prompt.
  Oversized tool results are elided; over budget, the first task turn + newest tail are kept.
- Guards & Detection:
  - **Thin-context refusal**: (free, once per transcript) refused if called before reading relevant files.
  - **`@advisor` bypass**: user turns containing `@advisor` skip thin-context refusal so users can consult immediately.
  - **Discussion gate**: in brainstorm mode (or when `discussionGate: "always"`), drafts ≥ `discussionMinChars` (default 800 chars)
    prompt the agent to consult before the answer stands, then provide a short attributed follow-up.
  - **Mechanical stuck detection**: repeating identical tool failure signatures (normalized of timestamps, hex, paths, numbers)
    annotates the failing tool result with advice to consult before retrying. Resets when `advisor` runs.
  - **Hard deadline & Circuit breaker**: 2 failures → 30 min pause.
  - **Per-transcript budget**: `maxUses` (reset on `/new`, via `/advisor reset`, or via `uses/max ⟲` in the header).
- In-run review nudge (continuation): after a genuine user turn with ≥ `firstConsultGap` state-changing tool calls
  and no consult (or ≥ `reconsultGap` since the last one), the runner appends a review nudge in the same run
  when no user input is waiting. Never interrupts real user messages. Coding result turns (`[auto-coding-result]`)
  are nudged to inspect the diff (`coding_agent action="diff"`) and consult before recommending a merge.
- Inline consult cards (WebUI): calls to `advisor` render directly in the message activity timeline:
  - **Running**: clock icon + sheen label ("Đang hỏi advisor · {focus}").
  - **Advice card**: brain icon, focus title, `n/max` budget badge, model name, and 4-line collapsed markdown advice with expandable toggle.
  - **Status chip**: subtle status chips for `insufficient_context` ("chưa đủ ngữ cảnh"), `max_uses_exceeded` ("hết ngân sách"), or `advisor_error` ("lỗi advisor").

### Rooms
- A session becomes a room with `/room on`, or automatically when the user @mentions a
  configured agent id. Room tools and the coordinator directive appear only then.
- The session's agent is the **coordinator**. `room_delegate({agent, task})` queues a
  teammate; when the coordinator's turn ends, teammates run as inline subagents (own preset,
  persona `instructions`, subagent toolset + `room_state`/`room_delegate`), their replies are
  posted to the chat with attribution, then an `[auto-room]` review turn re-summons the
  coordinator. Teammates can delegate onward and `WAIT_FOR @id` on data dependencies.
  Chained turns are budgeted per user message (`maxChainedTurns`).
- Storage: `<workspace>/.coworker/rooms/<room>.state.json` and `.transcript.jsonl`.
  `/room reset` clears them.
- Differences from AICoworker: teammates are personas over nanobot presets (nanobot has no
  multi-agent registry); no remote/federated agents; no direct `@agent` bypass of the
  coordinator.

### Addressing agents with `@`
The composer offers `@agy`, `@pi`, `@advisor` and every configured room agent (from `mentions[]` in the
session status). A room agent id keeps its room behaviour. The others are routed by a one-line note appended
to that user message (never to the system prompt, so the cached prefix is untouched):
- `@agy` / `@pi`: the coordinator delegates the request to that backend with `coding_agent(action="start")`.
  If coding is disabled the note says so and points at Settings → Capabilities → Coworker → Coding.
- `@advisor`: the coordinator consults the advisor with the question and reports where it agrees or disagrees.
  If the advisor is off the note says how to turn it on.
The coordinator still performs the hand-off; there is no direct bypass of it.

### Token cache & trim
One rule, from AICoworker: **a change to the cached prompt prefix is adopted only while the
provider cache is cold** (idle > TTL, default 300 s). While warm, the previously adopted
payload shape is re-applied verbatim, so trimming never busts a live cache.
- Trim keeps ≤ `maxTurns` user turns, cutting whole blocks of `maxTurns/2` at user-turn
  boundaries (≈ one cache miss per block instead of one per turn).
- Optimize drops no-op exchanges (`HEARTBEAT_OK`/`NO_REPLY`), empty assistant stubs and
  failed tool round-trips; shrinks one-shot heredoc scripts and > 20 k-char results in place.
  The live turn is never touched; tool call/result pairing is preserved.
- `mark_context_wasted(recent|ids)` (visible when `optimize` is on) lets the agent flag
  dead-end round-trips; applied at the next cold moment.
- `freezeSystemPrompt` (off by default) holds a drifted system prompt while warm; it is
  adopted immediately when the history after it was rewritten (compaction/summary).
- Keep-alive prompt caching (off by default) prevents provider prompt cache from expiring:
  - `strategy: "ping"` (default): replays the last request with a tiny ping shortly before TTL
    expiry, bounded by `windowMinutes`/`maxPings`/`leadSeconds` — ideal for standard 5-minute provider caches.
  - `strategy: "ttl1h"`: enables Anthropic 1-hour prompt cache retention (`cache_retention="long"`).
    Supported Anthropic models (`claude-3-7-sonnet`, `claude-3-5-sonnet`, `claude-3-5-haiku`, `claude-opus-3`)
    retain prompt cache for 1 hour without requiring repeated ping requests.
  - Per-session toggle: `/ctx keepalive on|off` or via the inspector popover.
- Auto-optimize toggle: `/ctx optimize on|off` or via the inspector popover allows disabling optimization per session.
- Only the outgoing payload changes; the session transcript is never modified. Providers
  with server-side conversation state (`stateful=True`) are not trimmed.
- `/ctx` shows the per-session optimizer and keep-alive state.
- The inspector also shows what the **provider** reported for the session (`caching.usage`): hit rate, tokens
  read from cache, tokens newly written, input total, the last request and a bar per recent request. It is
  kept in memory per session (lost on restart), and providers that return no cache fields are shown as
  "not reported" rather than as 0%. The header inspector button shows the session hit rate.

### Workflows
- Location: `<workspace>/workflows/<slug>/` (ref `<slug>`) or
  `<workspace>/skills/<skill>/workflows/<slug>/` (ref `skill:<skill>/<slug>`).
- `workflow_run(action=list|start|status|cancel)` or `/workflow list | run <ref> [input] |
  status | cancel | resume | repin | save <slug>`.
- After `start`, the harness injects one `[auto-workflow:<wf>:<step>]` turn per step. The
  model does the work and ends with a ```json block; the engine validates it against the
  step's `## Output` schema and graph edges (decision routes, parallel fan-out, joins,
  `max_attempts`, `on_fail`). Rejections re-prompt with the exact errors
  (`stepMaxRetries`), then fail the step deterministically. Human steps pause until the
  user replies. Runs are pinned to the graph fingerprint (`/workflow repin` to accept edits).
- Scheduled runs: a cron message containing `[auto-workflow-cron:<ref>] <input>` starts the
  run in that session.
- Save as workflow: `workflow_distill(slug)` or `/workflow save <slug>` writes
  `workflows/<slug>-draft/` with one step per genuine user turn (tools used + conclusion
  excerpt) for the user to generalize.
- Run state: `<workspace>/.coworker/workflow-runs/<slug>/<run-id>/{run.json,trace.jsonl}`.

### Coding agent (Pi & agy)

Delegate heavy coding work (multi-file edits, large refactors, bug fixes requiring a test/acceptance loop)
to an external coding harness running headless in an isolated git worktree, while nanobot coordinates,
verifies the results, and reports back in chat.

#### Backends supported
- **Pi** (`pi`): Lean, fast, steerable in-flight edits (`--mode rpc`).
- **agy** (`agy`): Google Antigravity CLI with broad research capabilities (`--output-format stream-json`).

#### Setup steps
1. **Install and authenticate harnesses outside nanobot**:
   - Pi: `npm install -g --ignore-scripts @earendil-works/pi-coding-agent`, configure credentials via `pi auth`.
   - agy: install `agy` binary, complete interactive login in a terminal.
2. **Configure repositories in `~/.nanobot/coworker.json`**:
   ```json
   {
     "coding": {
       "enabled": true,
       "default_backend": "pi",
       "repos": [
         {
           "path": "/path/to/your/git/repo",
           "base_ref": "main",
           "acceptance": "pytest -q"
         }
       ],
       "pi": {
         "allow_unsandboxed": true
       },
       "agy": {
         "allow_unsandboxed": true
       }
     }
   }
   ```

#### Usage
- **Agent tool**: `coding_agent(action="start", task="...", backend="pi|agy", acceptance="...")`
  Starts a task in the background. The LLM ends its turn immediately and is automatically re-summoned
  with `[auto-coding-result]` once the harness completes and nanobot verifies acceptance.
  Other actions: `status`, `steer` (Pi), `abort`, `result` (summary + diffstat + acceptance) and
  `diff` (read-only full diff, capped at 20 000 chars — read it before asking the advisor to review,
  since the advisor only sees what the agent has seen).
- **Slash commands**:
  - `/code list`: list active and recent coding tasks.
  - `/code status <id>`: check status, commits, and diffstat of a task.
  - `/code diff <id>`: inspect full git diff.
  - `/code steer <id> <message>`: steer a running Pi task mid-flight.
  - `/code abort <id>`: abort an active task.
  - `/code merge <id>`: squash-merge verified task changes into the base branch and clean up worktree.
  - `/code discard <id>`: discard worktree and delete the task branch.
  - `/code resume <id> <message>`: resume an interrupted or failed task with a new round.

#### Multi-agent room integration
A teammate in `room.agents` can have `backend: "pi"` or `backend: "agy"` configured. When the room
coordinator delegates a coding sub-task to that teammate, it runs through the coding runner with
isolated worktree and acceptance verification.

## WebUI

- **Settings → Capabilities → Coworker** edits `coworker.json` (Advisor, Team, Coding, and Cache tabs). Sections are
  validated as `CoworkerConfig`, preset names and repositories are checked (repos must be absolute git
  work trees), credential-looking `passEnv` names are refused, and the file is written atomically with
  unknown keys preserved. Changes apply without a restart. API: `GET /api/settings/coworker`,
  mutation `settings.coworker.update` (`POST /api/settings/coworker/update`).
- **Apps → Coding** shows Pi and agy (binary path/version; custom commands are located but never run).
- **Participants**: the chat header shows chips for the agents taking part in the session (coordinator,
  advisor mid-consult or reviewing, teammates working/queued/waiting, coding tasks with tool count and last tool); the
  inspector lists them in detail. The **Advisor** button next to it is the manual per-session switch
  (mutation `session.coworker.advisor`, body `{enabled?, preset?, mode?, reset_uses?}`). It displays
  the current consult count (`uses/max`), with a reset icon `⟲` when the budget is spent.
- **Activity Timeline**: tool calls to `advisor` render dedicated consult cards: in-progress consultation indicator with clock,
  collapsible advice card with model and budget counters, and unobtrusive chips for non-advice statuses. Data comes from `participants[]` in
  `GET /api/sessions/{key}/coworker` and is polled every 3 s only while something is active.

## Tests

`tests/coworker/` — seams, optimizer gating, workflow engine/drive/distill, advisor guards,
room scheduling (chaining, WAIT_FOR, budget), hook orchestration, and coding harness delegation
(`tests/coworker/coding/`).

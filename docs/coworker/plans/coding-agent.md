# Implementation plan — `coding_agent` tool with Pi and agy backends

Status: **planned, not started**. Written 2026-09-30 for a coding agent to execute later.
Target branch: create `feat/coding-agent` from `feat/coworker` (it builds on the coworker extension).
Supersedes the earlier Pi-only draft (`coding-agent-pi.md`).

## 1. Goal

Let nanobot delegate real coding work (multi-file edits, refactors, bug fixes with a test
loop) to an external **coding harness** running headless, while nanobot stays the
orchestrator: it writes the brief, isolates the work, verifies the result itself, reports
back in chat, and lets the user merge. Two backends, selectable per task / per repo:

- **Pi** — https://pi.dev, npm `@earendil-works/pi-coding-agent`, binary `pi`.
- **agy** — Google Antigravity CLI, binary `agy` (installed on the dev machine:
  `~/.local/bin/agy`, version **1.2.13**).

```
user (Telegram/Zalo/WebUI) ─► nanobot session ─► coding_agent(start, brief, backend?)
                                                   │
                     git worktree + branch ◄───────┤  backend process (cwd = worktree)
                                                   │    pi: --mode rpc (JSONL both ways)
                                                   │    agy: -p --output-format stream-json
                     nanobot runs acceptance cmd ◄─┤  completion event
                                                   ▼
                    [auto-coding-result] turn ─► coordinator reviews (advisor) ─► /code merge <id>
```

### Non-goals (v1)
- No Claude Code / Codex backends yet — the backend interface must allow them.
- No SDK embedding (Node/Go in-process); drive the CLIs as subprocesses only.
- No automatic merge. Merging is always an explicit user command.
- No WebUI screens.
- No "run both backends and compare" mode yet (see §8, future).

## 2. Hard constraints (read before coding)

1. **Merge safety** (see `docs/coworker/README.md`): add NO new edits to upstream files.
   Everything goes in `nanobot/coworker/coding/` plus one new import line in the existing
   shim `nanobot/agent/tools/coworker.py` and one `register` call in
   `nanobot/coworker/commands.py`. If you believe a core change is needed, stop and ask.
2. Follow `AGENTS.md` / `.agent/design.md`: Python 3.11, asyncio, ruff (E,F,I,N,W, 100 cols),
   basedpyright **strict** — CLI output is an untrusted boundary: parse into dataclasses /
   `TypedDict` once in the backend module, use `as_dict`/`as_list` from
   `nanobot/coworker/transcript.py`; every `cast` needs a runtime check.
3. Config lives in `~/.nanobot/coworker.json` (`CoworkerConfig` in
   `nanobot/coworker/config.py`), never in `nanobot/config/schema.py`. Feature **off by default**.
4. Neither harness gives nanobot a usable approval loop (Pi has none by design; agy's
   approval prompts cannot be answered headless). Isolation is our job — worktree always,
   OS sandbox when configured (§9.1).
5. **Each harness is configured and authenticated outside nanobot** (decision 2026-09-30).
   The user logs in, picks the model/effort and sets permissions inside Pi / agy themselves.
   nanobot never passes model, provider, thinking/effort, API-key flags or provider API-key
   env vars, and never reads or writes the harnesses' credential files.

## 3. Verified facts (pin and re-verify at M0)

### 3.1 Pi (from docs of `@earendil-works/pi-coding-agent@0.81.1`; not installed locally)

Sources: `https://cdn.jsdelivr.net/npm/@earendil-works/pi-coding-agent@0.81.1/docs/rpc.md`,
`.../README.md`, https://pi.dev/docs/latest/rpc. Re-read for the installed version at M0.

- Install: `npm install -g --ignore-scripts @earendil-works/pi-coding-agent`.
- Modes: interactive, `-p/--print`, `--mode json`, **`--mode rpc`** (JSONL commands on stdin,
  responses + events on stdout), SDK.
- Flags we use: `--mode rpc`, `--session-dir <path>`, `--session <path|id>` (resume),
  `--name <name>`, `--tools <list>` (built-ins read, bash, edit, write, grep, find, ls),
  `--no-extensions`, `--no-approve` (ignore project-local `.pi/`), `--append-system-prompt`.
  Flags we deliberately never use: `--provider`, `--model`, `--thinking`, `--api-key` (§2.5).
- Config dir `~/.pi/agent/` (override `PI_CODING_AGENT_DIR`). Loads `AGENTS.md`/`CLAUDE.md`
  from global dir, parents and cwd.
- Framing: strict JSONL, split on `\n` only, strip trailing `\r`; never split on U+2028/2029.
- Commands (optional `id` echoed in the response): `prompt {message}`, `steer {message}`,
  `follow_up {message}`, `abort`, `get_state`, `get_last_assistant_text`, `get_session_stats`.
- Responses: `{"type":"response","command":…,"success":bool,"id"?,"error"?,"data"?}`.
- Events: `agent_start`, `agent_end`, **`agent_settled`** (= run fully done → completion),
  `turn_start/end`, `message_start/update/end` (`stopReason` stop|length|toolUse|error|aborted),
  `tool_execution_start/update/end` (`toolCallId`), `auto_retry_*`, `compaction_*`,
  `extension_error`.
- `extension_ui_request` dialogs (`select|confirm|input|editor`) **block until answered** —
  always reply `{"type":"extension_ui_response","id":…,"cancelled":true}`. Fire-and-forget
  (`notify`, `setStatus`, `setWidget`, `setTitle`, `set_editor_text`) need no reply.

### 3.2 agy (verified live on this machine, 2026-09-30, agy 1.2.13)

Sources: `agy --help` output; live runs recorded in `fixtures/agy-1.2.13/` (paths sanitized to
`/work/repo`); https://antigravity.google/docs/cli/headless.

- **Headless**: `agy -p "<prompt>"` (aliases `--print`, `--prompt`). With stdin from
  `/dev/null` and stdout redirected to a file (no TTY) it ran and exited 0 in 6 s — the
  non-TTY hang of issue google-antigravity/antigravity-cli#318 (v1.0.6) **did not reproduce**
  on 1.2.13. Keep the idle timeout anyway.
- Flags present in 1.2.13: `--output-format text|json|stream-json`, `--input-format
  text|stream-json` (stream-json input needs stream-json output; one NDJSON message per line,
  one turn each), `--print-timeout` (default `0s` = wait), `--conversation <id>` (resume),
  `-c/--continue`, `--dangerously-skip-permissions`, `--sandbox` (terminal restrictions),
  `--mode accept-edits|plan`, `--add-dir`, `--agent`, `--project`, `--new-project`,
  `--json-schema`, `--disable-slash-commands`, `--log-file`, `--model`, `--effort`.
  **Not present**: `--headless`, `--approve` (mentioned by some web articles — ignore them).
  No tool allowlist flag.
- **stream-json events** (one JSON object per line; see `fixtures/agy-1.2.13/*.jsonl`):
  - `{"event":"init","conversation_id":…,"init":{"cwd","tools":[…],"permission_mode"}}`
  - `{"event":"step_update","step_update":{"conversation_id","step_index","state":"ACTIVE|DONE",
    "step_type":"user_input|agent_response|tool", "text_delta"?, "tool_name"?,
    "tool_info":{"name","parameters"}?, "duration_seconds"?, "usage"?}}`
    Tool parameters seen: `write_to_file {TargetFile}`, `run_command {CommandLine}`.
    `usage = {input_tokens, output_tokens, thinking_tokens, cache_read_tokens, total_tokens}`.
  - `{"event":"result","result":{"conversation_id","status":"SUCCESS",…,"response",
    "duration_seconds","num_turns","usage"}}` — **completion**. Only `SUCCESS` was observed:
    treat any other status, a non-zero exit, or EOF without `result` as failure and keep the
    raw line in the task record.
- `--output-format json` prints only the final `result` object (fixture `resume-json.json`).
- **Resume**: `agy -p "<follow-up>" --conversation <id>` continued the same conversation (it
  remembered the file it created). `num_turns` and `usage` in the result are **cumulative
  for the conversation** — store per-round deltas yourself.
- **Permissions**: the user's `~/.gemini/antigravity-cli/settings.json` currently has
  `toolPermission: always-proceed` and `agentMode: accept-edits`, which is why the tool test
  did not block. The `init.permission_mode` field reports the effective mode. Do not rely on
  the user's setting: always pass `--dangerously-skip-permissions` (otherwise a user who
  changes the setting gets a silent headless hang) — this is safe only inside our isolation.
- `--sandbox` did not block `cat` inside cwd; its exact restrictions are undocumented. Treat
  it as defense in depth, not as the boundary.
- agy's toolset is broad (browser automation, `search_web`, `generate_image`, subagents,
  `schedule`, MCP). There is no allowlist flag; the OS sandbox is what constrains it.
- State/credentials: `~/.gemini/antigravity-cli/` (settings, conversations, logs, auth).
  Every headless run is recorded in the user's agy history.
- Model/effort: configured by the user in agy (§2.5); never pass `--model`/`--effort`.

## 4. Architecture

New package `nanobot/coworker/coding/`:

| File | Responsibility |
|------|----------------|
| `backends/base.py` | `CodingBackend` Protocol + shared types: `BackendRun` (async iterator of `BackendEvent`), `BackendEvent` (`progress`, `tool`, `text`, `done`, `error`), `BackendStats`, `BackendResult`. Methods: `start(brief, cwd, rules) -> BackendRun`, `follow_up(run_ref, message) -> BackendRun`, `steer(message)` (optional capability), `abort()`, `stats()`. `capabilities` flags: `steer`, `live_stats`. `backend_for(name)`. |
| `backends/jsonl.py` | Shared strict-JSONL reader (bytes, `readuntil(b"\n")`, big limit, strip `\r`, decode UTF-8) and process-group spawn/terminate helpers (`start_new_session=True`, SIGTERM → wait → SIGKILL). |
| `backends/pi.py` | `PiBackend`: long-lived `pi --mode rpc` process; request/response correlation by `id`; auto-cancel `extension_ui_request` dialogs; `prompt` / `steer` / `abort` / `get_session_stats` / `get_last_assistant_text`; completion on `agent_settled`; resume via `--session <path>`. |
| `backends/agy.py` | `AgyBackend`: one `agy -p … --output-format stream-json --dangerously-skip-permissions [--sandbox]` process **per round**; parse `init` / `step_update` / `result`; capture `conversation_id` from `init`; follow-up round = new process with `--conversation <id>`; abort = terminate the process group; stats from `result.usage` (diff against the previous round, since it is cumulative). `steer` not supported in v1 (capability false → tool returns a clear error; the user can `abort` + `resume <msg>`). |
| `workspace.py` | Git worktree lifecycle: validate repo against `repos`, `git worktree add` on branch `coworker/code/<task>` from the base ref, diff/diffstat/changed files/commit list, run acceptance, merge (squash default) and cleanup. All git via `asyncio.create_subprocess_exec`. |
| `tasks.py` | `CodingTask` record (id, backend, session_key, route, repo, base, branch, worktree, brief, status, timestamps, backend resume ref — Pi session path or agy conversation id —, per-round stats, result) persisted to `<workspace>/.coworker/coding-tasks/<id>.json`; live registry; restart recovery; concurrency limits. |
| `runner.py` | Backend-neutral driver (§7). |
| `brief.py` | Brief + RULES rendering. Pi gets RULES via `--append-system-prompt`; agy has no such flag → prepend RULES to the prompt text of the first round. |
| `tools.py` | `CodingAgentTool` (`coding_agent`). |
| `commands.py` | `/code list | status <id> | diff <id> | steer <id> <msg> | abort <id> | merge <id> | discard <id> | resume <id> <msg>`. |

Reuse from the coworker extension: `runtime.inject_turn`, `runtime.post_to_chat`,
`runtime.spawn_background`, `runtime.services()`, `tools_base.CoworkerTool`,
`transcript.as_dict/as_list`, `hook.CoworkerHook` (tool visibility), `directives.py`.

## 5. Configuration (add to `CoworkerConfig`)

```python
class PiBackendConfig(Base):
    command: list[str] = ["pi"]            # argv prefix; tests point this at a fake script
    agent_dir: str | None = None           # sets PI_CODING_AGENT_DIR; None = Pi default
    tools: list[str] | None = None         # --tools allowlist; None = Pi default
    extensions: bool = True                # the user's own Pi setup; False → --no-extensions
    trust_project_files: bool = False      # False → --no-approve
    pass_env: list[str] = []               # extra env var NAMES to forward
    allow_unsandboxed: bool = False        # run even when coding.sandbox == "none"

class AgyBackendConfig(Base):
    command: list[str] = ["agy"]           # argv prefix; tests point this at a fake script
    agy_sandbox: bool = True               # adds agy's own --sandbox (defense in depth)
    mode: Literal["accept-edits"] | None = None   # --mode; None = user's agy setting
    extra_args: list[str] = []             # e.g. ["--disable-slash-commands"]; validated
                                           # against a denylist: --model, --effort, -p, --print,
                                           # --prompt, --output-format, --conversation, -c, --continue
    pass_env: list[str] = []
    allow_unsandboxed: bool = False

class RepoConfig(Base):
    path: str                              # absolute; must be a git repo
    acceptance: str | None = None          # default acceptance command for this repo
    base_ref: str = "HEAD"
    backend: Literal["pi", "agy"] | None = None   # per-repo default backend

class CodingAgentConfig(Base):
    enabled: bool = False
    default_backend: Literal["pi", "agy"] = "pi"
    pi: PiBackendConfig = PiBackendConfig()
    agy: AgyBackendConfig = AgyBackendConfig()
    repos: list[RepoConfig] = []           # explicit allowlist; EMPTY = every start is refused
    worktree_root: str | None = None       # default <workspace>/.coworker/code-worktrees
    sandbox: Literal["none", "bwrap"] = "none"  # nanobot's OS sandbox, see §9.1
    timeout_minutes: int = 45              # hard wall clock per task
    idle_timeout_minutes: int = 10         # no event for this long → abort
    max_concurrent_per_session: int = 1
    max_concurrent_total: int = 2
    fix_rounds: int = 1                    # follow-up rounds when acceptance fails
    progress_every_seconds: int = 60       # throttle chat progress notes
    merge_strategy: Literal["squash", "no-ff", "ff-only"] = "squash"
    delete_branch_after_merge: bool = True
    keep_failed_worktrees_days: int = 3
```

Backend resolution for a task: tool arg `backend` → repo's `backend` → `default_backend`.
A backend whose binary is not on PATH is reported as unavailable (never silently swapped).
Add `coding: CodingAgentConfig` to `CoworkerConfig`; document it in `docs/coworker/README.md`.

## 6. Tool contract — `coding_agent`

Visible only when `coding.enabled` (hide it in `CoworkerHook.transform_request`, like the
other feature tools; add `"coding_agent"` to a `CODING_TOOLS` set).

```jsonc
{
  "action": "start | status | steer | abort | result",
  "task": "…",            // start: goal, concrete and self-contained
  "backend": "pi | agy",  // start: optional; see resolution order in §5
  "repo": "/abs/path",    // start: a configured repos[].path (optional if exactly one)
  "base": "main",         // start: optional base ref
  "acceptance": "…",      // start: optional; defaults to the repo's acceptance command
  "files": ["src/a.py"],  // start: optional hints
  "wait": false,          // start: true = block until done (only if timeout_minutes <= 10)
  "id": "ct-…",           // status/steer/abort/result
  "message": "…"          // steer (Pi only in v1)
}
```

- `start` returns immediately `{status:"started", id, backend, branch, worktree}` (async by
  default, like `spawn`). Directive: "after starting, END your turn; you will be re-summoned
  with the result — never poll".
- `steer` on an agy task → `{status:"error", error:"agy tasks cannot be steered mid-run; use
  abort then /code resume <id> <message>"}`.
- `result` returns the stored summary + diffstat + acceptance output (truncated; full diff
  via `/code diff`). `merge`/`discard` are slash commands only (user decision).

Directive (`CODING` in `directives.py`, appended when enabled): when to delegate
(multi-file edits, refactors, bug fixes needing a test loop) vs. doing it yourself (one-line
edits, config tweaks); list available backends with a one-line hint each (Pi: steerable,
lean toolset; agy: broad toolset incl. browser/web research); always pass `acceptance` when
the repo has tests; review the returned diff before recommending a merge; ask the advisor.

## 7. Task lifecycle (runner.py, backend-neutral)

1. **Admit**: enabled; repo in `repos`; backend resolved and its binary on PATH (error text
   points to "install and log in to <backend> in a terminal first"); `git rev-parse
   --show-toplevel` ok; concurrency limits; prune expired failed worktrees. Allocate id
   `ct-YYYYMMDD-HHMMSS-xxxx`.
2. **Isolate**: `git worktree add -b coworker/code/<id> <worktree_root>/<id> <base>`.
3. **Launch** (child env for both: minimal base `PATH`, `HOME`, `USER`, `LANG`, `TERM=dumb`
   + backend `pass_env` names; nanobot's provider keys never forwarded; `cwd` = worktree;
   stdin a pipe for Pi, `/dev/null` for agy):
   - Pi: `command + ["--mode","rpc","--session-dir",<tasks>/<id>/pi-sessions,"--name",<id>]
     + ["--tools",…]? + ["--no-extensions"]? + ["--no-approve"]? + ["--append-system-prompt",
     RULES]`, `PI_CODING_AGENT_DIR` if `agent_dir`; send `prompt` with the brief.
   - agy: `command + ["-p", RULES + brief, "--output-format","stream-json",
     "--dangerously-skip-permissions"] + ["--sandbox"]? + ["--mode", mode]? + extra_args`.
     (Prompt goes in argv; if it exceeds ~100 kB, use `--input-format stream-json` with one
     message on stdin instead — verify the input message shape at M0.)
   - If `sandbox == "bwrap"`, wrap via `nanobot/agent/tools/sandbox.py` (verify
     `wrap_command`'s signature; build the string with `shlex.join`). Binds: worktree rw,
     repo `.git` rw, harness state dir rw (Pi agent dir / `~/.gemini/antigravity-cli`, for
     token refresh and conversation storage), harness install dir + node ro. Network on.
4. **RULES** (both): work only inside cwd; run the acceptance command before finishing;
   **commit** changes on the current branch with a clear message; never push; never touch
   files outside the repo; do not use browser/image/scheduling tools unless the task needs
   them (agy); end with a short summary of what changed and what is left.
5. **Monitor**: consume `BackendEvent`s until `done`/`error`. Track tool count and last tool
   (Pi `tool_execution_*`; agy `step_update` with `step_type:"tool"` → `tool_name` +
   `TargetFile`/`CommandLine`). Every `progress_every_seconds` post one line to chat
   (`🛠️ ct-… [agy] run_command: pytest (12 tools, 4m)`). Pi: auto-cancel UI dialogs.
   Enforce `timeout_minutes` and `idle_timeout_minutes` → Pi: `abort`, wait 10 s; agy:
   SIGTERM; then kill the process group.
6. **Verify** (nanobot, not the harness): commit any uncommitted changes as
   `coworker: uncommitted changes from <backend>`; diffstat `base...branch`, changed files,
   commits. Run `acceptance` (same sandbox, timeout, output cap). On failure with
   `fix_rounds` left: Pi → `prompt` in the same process; agy → new round with
   `--conversation <id>`; message = failing output tail (4k chars). Loop to 5.
7. **Stats**: Pi `get_session_stats` + `get_last_assistant_text`; agy `result.usage`
   (per-round deltas) + `result.response`.
8. **Deliver**: status `succeeded | failed_acceptance | aborted | timed_out | error`. Inject
   `[auto-coding-result]` (kind `coding_result`) into the originating session: goal, backend,
   status, harness summary, commits, diffstat, acceptance result, tokens/cost, and "review,
   then tell the user to `/code merge <id>` or `/code discard <id>`". Add
   `[auto-coding-result]` to `transcript.AUTO_MARKERS`. `wait=true` returns the text instead.
9. **Shutdown**: Pi — close stdin, wait 5 s, kill. agy — process already exited per round.

Restart recovery: at first coworker tool creation after boot, mark `running` tasks
`interrupted`. `/code resume <id> <msg>`: Pi relaunches with `--session <saved path>`; agy
runs a new round with `--conversation <saved id>` — both in the same worktree.

Cancellation stays explicit (`coding_agent(action="abort")`, `/code abort <id>`); a
cancelled nanobot *turn* must not kill a running *task*.

## 8. Integrations

- **Advisor**: nothing to build; `coding_agent` is a work tool (not in `NON_EVIDENCE_TOOLS`)
  and the result turn carries the diffstat for the advisor to review.
- **Rooms**: optional `backend: "pi" | "agy"` on `RoomAgentConfig`; `_run_guest` then runs the
  delegation through the coding runner with `wait=True` semantics. Suggested roster:
  `coder-pi` (lean, steerable edits) and `coder-agy` (broad toolset, web research + code).
- **Workflows**: no engine change; ship a sample under `docs/coworker/examples/code-change/`
  (a task step calling `coding_agent` with `wait=true`, a decision step routing on
  `tests_passed`).
- **Cron**: works as-is.
- **Future (not v1)**: `second_opinion` — run both backends on the same brief in two
  worktrees, ask the advisor to compare the diffs, present both to the user.

## 9. Security checklist

- Repo must resolve (realpath) to a configured `repos[].path`; reject symlink escapes.
- Worktree root git-ignored or outside tracked trees (`.coworker/`).
- Child env is an allowlist; nanobot's provider keys never reach a harness.
- Neither harness asks before acting (agy runs with `--dangerously-skip-permissions` and a
  broad toolset: browser, web, MCP, scheduling). A task starts only when `sandbox == "bwrap"`
  **or** that backend's `allow_unsandboxed` is true (default false for both).
- Never log brief/outputs when `tool_log_content_allowed()` is false.
- Branch names only from our id alphabet; git/harness calls via exec (no shell), except the
  user's `acceptance` command, which runs through nanobot's sandbox wrapper.
- `extra_args` validated against the denylist in §5.
- Merge only via `/code merge <id>` (§9.2).

### 9.1 Isolation per environment (decision 2026-09-30)

| Environment | `sandbox` | Why |
|-------------|-----------|-----|
| Dev machine (Linux) | `bwrap` | nanobot's existing exec sandbox; cheap, per task. |
| Self-hosted `docker compose` + `docker-compose.bwrap.yml` | `bwrap` | That override grants `SYS_ADMIN` + unconfined seccomp/apparmor for bwrap. |
| Render (`runtime: docker`) | `coding.enabled: false` | No `SYS_ADMIN`, no Docker socket, runtime image has no Node/Pi/agy, repos live on the dev machine. |

Docker-per-task is not recommended (heavy, needs a root-equivalent Docker socket, credential
dirs would have to be mounted into every task).

### 9.2 Merge policy (decision 2026-09-30)

- `squash` by default: one commit on the user's branch = task goal + harness summary +
  `Task: <id>` + `Backend: <name>`; the task record keeps the branch's commit list.
- `/code merge <id>` runs in the repo's main checkout; requires it to be on the task's base
  branch with a clean tree, otherwise refuse with the reason (never stash/reset). Conflicts →
  abort the merge, report files.
- After merge: remove worktree, delete branch. `/code discard <id>` removes both now; failed
  tasks keep their worktree `keep_failed_worktrees_days`.
- Merging into the checkout the gateway runs from only takes effect after restart — say so.

## 10. Tests (`tests/coworker/coding/`)

Two fake harnesses, driven by a scenario file path in an env var, pointed to by
`coding.<backend>.command = [sys.executable, <fake>.py]`:

- `fake_pi.py` — speaks Pi RPC: acknowledges `prompt`, emits event sequences, edits/commits
  files in cwd, emits an `extension_ui_request` confirm dialog and waits for the answer,
  hangs (timeouts), emits malformed / `\r\n` / U+2028-containing lines, answers
  `get_session_stats` and `get_last_assistant_text`.
- `fake_agy.py` — parses the argv like agy (`-p`, `--output-format`, `--conversation`,
  `--dangerously-skip-permissions`, `--sandbox`), replays event shapes **copied from
  `docs/coworker/plans/fixtures/agy-1.2.13/`** (move them to `tests/coworker/coding/fixtures/`),
  edits/commits files, supports resume by conversation id, can exit non-zero, end without a
  `result`, emit a non-SUCCESS status, or hang.

Required cases:
1. Pi parser: responses, events, unknown events ignored, malformed → None, `\r\n`, U+2028.
2. agy parser: `init` / `step_update` (user_input, agent_response, tool) / `result`, parsed
   from the real fixtures; cumulative usage converted to per-round deltas.
3. Happy path per backend on a temp git repo: worktree + branch → fake commits → acceptance
   passes → `[auto-coding-result]` with diffstat and `succeeded`; record persisted.
4. Uncommitted changes are committed by nanobot.
5. Acceptance fails → follow-up round (Pi: same process; agy: `--conversation <id>`) → passes.
6. Pi UI dialog auto-cancelled (no hang).
7. Timeouts: idle and wall → Pi `abort` then kill; agy SIGTERM then kill; `timed_out`.
8. agy failure modes: non-zero exit, missing `result`, status ≠ SUCCESS → `error` with raw line.
9. Env/argv hygiene per backend: a dummy `ANTHROPIC_API_KEY`/`GEMINI_API_KEY` in the test
   process is absent in the child; argv never contains `--model`, `--effort`, `--provider`,
   `--thinking`, `--api-key`; agy argv always contains `--dangerously-skip-permissions`.
10. `extra_args` denylist rejects `--model` etc. at config validation.
11. Backend resolution order (arg → repo → default); unavailable binary → clear error.
12. `steer` on agy → capability error; on Pi → forwarded.
13. Unsandboxed start refused unless `allow_unsandboxed` for that backend.
14. Concurrency limit; repo allowlist incl. symlink escape; empty `repos` refuses.
15. `/code merge` squash + cleanup; refused on dirty/other-branch checkout; conflict aborted.
    `/code discard`.
16. Restart recovery → `interrupted`; `/code resume` uses the saved Pi session / agy
    conversation id.
17. Tool visibility via hook; `wait=true` returns inline without injecting.

Plus: ruff, basedpyright strict on `nanobot/coworker`, `pytest tests/coworker -q`, full suite
(`pytest -n auto`; known unrelated failures: `test_webui_missing_runtime_env_fails_before_
starting_gateway` fails on clean HEAD; nutritech/matrix tests are environment-dependent).

Manual live smoke (not CI): with each backend, ask nanobot in the CLI channel to "add a
--version flag to scripts/foo.py with a test" on a throwaway repo and watch the flow.

## 11. Milestones

| # | Deliverable | Done when |
|---|-------------|-----------|
| M0 | Install Pi; re-verify §3.1 against `pi --help`/rpc.md; re-run `agy --help` and the three agy probes (print, tools, resume) if agy was upgraded; verify `--input-format stream-json` message shape | §3 matches reality |
| M1 | `backends/jsonl.py`, `backends/base.py`, `backends/pi.py`, `backends/agy.py`, both fakes + tests 1, 2, 6–10, 12 | Both clients drive their fakes reliably |
| M2 | `workspace.py`, `tasks.py`, `runner.py`, `brief.py` + tests 3–5, 11, 13, 14, 16 | Async task delivers `[auto-coding-result]` for both backends |
| M3 | `tools.py`, `commands.py`, config, hook visibility, directive + tests 15, 17 | Usable from chat end to end |
| M4 | Docs (README section, setup steps per backend, sample workflow), room `backend` field | Docs reviewed |

Commit per milestone on `feat/coding-agent`, style `feat(coworker): …`, with the
`Co-Authored-By` trailer your harness requires.

## 12. Decisions (2026-09-30)

1. **Auth** — each harness is logged in by the user in a terminal, outside nanobot (Pi:
   `/login` into its agent dir; agy: interactive `agy` login into `~/.gemini/antigravity-cli`).
   nanobot passes no credentials.
2. **Model / provider / thinking / effort** — configured inside each harness only.
3. **Repos** — explicit `repos` allowlist, empty = disabled. First entry: the nanobot repo
   (`/home/cuongpt/nanobot`, acceptance `uv run --no-sync pytest tests/coworker -q`).
4. **Merge** — `squash`, delete branch + worktree after merge, strict clean-checkout rule (§9.2).
5. **Isolation** — bwrap on the dev machine and self-hosted compose; disabled on Render (§9.1);
   unsandboxed runs need an explicit per-backend opt-in.
6. **Backends** — Pi and agy side by side; default `pi`, overridable per repo and per task.
   agy always runs with `--dangerously-skip-permissions` inside the isolation above.

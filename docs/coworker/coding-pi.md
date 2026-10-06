# Coding with Pi (runtime v2)

nanobot delegates multi-file coding to **Pi** running headless in an isolated git worktree
(or in place for a non-git project). nanobot is the coordinator: it writes a structured
contract, drives a phase state machine, runs an **independent reviewer**, and reports back
in chat. Pi is the worker; a nanobot-owned Pi extension (`nanobot-bridge`) enforces policy
and the acceptance gate inside the Pi process.

Agy was removed; Pi is the only backend.

## Install and pin

```bash
npm install -g --ignore-scripts @earendil-works/pi-coding-agent
pi auth            # log in once, in a terminal
pi --version       # must be >= coding.pi.min_version (default 1.0.0)
```

nanobot spawns Pi with `--mode rpc`, talks JSONL over stdin/stdout, and loads
`nanobot/coworker/coding/pi/extension/nanobot-bridge.ts` with `--extension`.

## Diagnose with `/code doctor`

```
/code doctor
```

Checks, each reported with ✅/❌:

| Check | Meaning |
| --- | --- |
| `pi_binary` | the resolved `pi` binary exists |
| `pi_version` | `pi --version` >= `coding.pi.min_version` |
| `node` | Node is on PATH (Pi runs on Node) |
| `sandbox` | the configured OS sandbox can start a process here |
| `worktree_root` | the worktree root is writable |
| `extension` | `nanobot-mode` is loaded from `nanobot-bridge.ts` |
| `pi_login` | `get_available_models` returns at least one model |
| `trial_prompt` | a short prompt reaches `agent_settled` |

## Configuration

```json
{
  "coding": {
    "enabled": true,
    "repos": [{"path": "/abs/path/repo", "base_ref": "main", "acceptance": "pytest -q"}],
    "pi": {
      "command": ["pi"],
      "min_version": "1.0.0",
      "allow_unsandboxed": true,
      "phases": {
        "plan":      {"model": "anthropic/claude-opus-4", "thinking": "high"},
        "implement": {"model": "anthropic/claude-sonnet-4", "thinking": "medium"},
        "review":    {"model": "openai/gpt-5", "thinking": "high"}
      }
    }
  }
}
```

- **`coding.pi.phases.{plan,implement,review}.{model,thinking}`** — model (`"provider/modelId"`)
  and reasoning level per phase. `null`/empty uses Pi's default. The **reviewer should use a
  different model** from the implementer for an independent review. Editable in the WebUI
  (Settings → Capabilities → Coworker → Coding → *Model per phase*) and validated on save
  (format `provider/modelId`; values missing from the live model list are kept with a warning).
- Model list is served by `GET /api/settings/coworker/phase-models` (cached 10 minutes;
  `/refresh` forces a re-probe).

## Phases

`Prepare → Plan → AwaitApproval → Implement → Review → Fix → Deliver`. Every transition is
persisted to the tasks registry. `plan_approval` is `auto` by default (auto-approve short
plans with no open questions), `always`, or `never`.

- **Plan**: read-only; Pi ends with `report_result(kind='plan')`.
- **Implement**: Pi implements the approved plan; the extension's `agent_before_settle` gate
  runs the acceptance command and continues up to `settle_max_continuations` times.
- **Review**: a **fresh, no-session** Pi process (`--no-session`), review-mode contract,
  read-only, concludes with `report_result(kind='review', verdict='pass'|'changes_requested')`.
  It never sees the worker's transcript.
- **Fix**: blocking/major findings are fed back to the worker session; the loop runs up to
  `coding.fix_rounds` times.

## Contracts

Write contracts with `coding_agent(action="start", objective=…, context=…, acceptance_criteria=[…],
constraints=[…], out_of_scope=[…], acceptance=…, files=[…], mode="plan_first"|"auto")`.
The contract is written to `<workspace>/.coworker/coding-tasks/<id>/task-contract.json` and read
by the extension. A good contract has a measurable objective, a context section ≥
`coding.min_context_chars` characters, and verifiable acceptance criteria.

## Tasks, resume, observability

- `/code list | status <id> | diff <id> | steer <id> <msg> | abort <id>` — as before.
- `/code merge <id> | discard <id>` — merge or drop a worktree task.
- **`/code approve <id> [notes]` / `/code revise <id> <feedback>`** — continue a parked
  `plan_first` task (`awaiting_approval`): implement the plan, or re-run planning with feedback.
  The same actions exist on `coding_agent`. `/code resume` still refuses unapproved plans.
- **`/code resume <id> [message]`** — after a gateway restart, in-flight (`started`/`running`)
  tasks are marked `interrupted` and the chat is notified. Resume re-attaches with `--session`,
  reconciles the session via `get_entries`, continues the worker (`follow_up`), re-runs the
  reviewer, and delivers. A task in `AwaitApproval` is not spawned until it is approved.
- Each finished run is recorded in the `coding_runs` table (`coworker_metrics.sqlite3`): status,
  fix rounds, settle continuations, blocked calls, questions, per-phase tokens/cost/time. The
  inspector shows the current phase, pending questions, and the exported session HTML path.

## Safety

- The `nanobot-bridge` extension **enforces** policy in-process: writes outside `write_roots`
  and `deny_commands`/`deny_read` matches are blocked and counted; plan/review modes block all
  writes. The OS sandbox (`coding.sandbox`) is the second layer.
- Pi runs with a minimal environment; only `coding.pi.pass_env` names are forwarded (credentials
  are refused by settings validation).

# Coworker eval baseline: findings

Source: `docs/coworker/plans/archive/eval/coworker-eval-baseline.json` (7 scenarios x 2 runs = 14 runs; metadata git_commit `04a17a3a`; committed as `8d3e2a51`, not pushed).
Eval config: runner `gemini-3.8-flash-tiered`, advisor `claude-sonnet-5-5`, judge `claude-opus-5-5`.

Status: the baseline is UNOFFICIAL. Update 09/10/2026: problems 1 and 2 are fixed in the harness (commit ddc8d836): specialist deliverables are passed to the judge, the judge is a tool-less direct call, and a parse or call failure becomes judge_error (excluded from means), never 3.0. Covered by tests/coworker/eval/test_eval_harness.py::test_judge_is_a_direct_call_that_retries_and_never_defaults. Not fixed: problems 3-7, a re-run is still needed, and the judge scores the final answer, not the advisor consult quality.
Certainty tags: [observed] seen in data; [likely] strong inference, mechanism not proven; [unknown].

## Quality means (14 runs)

| Filter | Mean | Runs kept |
|---|---|---|
| All runs | 2.89 | 14 |
| Excluding the 10 judge parse-failure fallbacks | 2.63 | 4 (2.0, 3.5, 2.8, 2.2) |
| Excluding parse failures and timeouts | 2.33 | 3 (crm R1 2.0, persona-nutri R2 2.8, script-update R2 2.2) |

Edutech R2 (3.5) timed out but has a valid judge verdict. Parse failures and room timeouts are separate problems; do not conflate them.

## Problems

1. **Judge does not see the specialists' deliverables** [likely]
   - `scripts/coworker_eval.py:443`: `transcript = result.content`, taken from the first `bot.run`.
   - `wait_room_settled` (90s timeout) returns only a bool, so specialist outputs are never collected.
   - The judge sees the handoff text plus `delegations_recorded`.
   - Judge scores of 1.0 for Personalization/CTA in crm R1 and script-update R2 are consistent with this.
   - The line content was re-verified; the causal link to the scores was not.

2. **Judge parse failure: 10/14 runs** [observed, mechanism unproven]
   - `_judge_eval` runs the judge through a full `AgentLoop`, so the raw text contains "Advisor review...".
   - `_parse_judge_response` falls back to `3.0` with empty `criteria_scores` on failure, which inflates the means.

3. **Room `timed_out`: 9/14 runs** [observed]
   - By specialist count (timed_out / runs): 0 specialists 0/2, 1 specialist 1/4, 2 specialists 6/6, 3 specialists 2/2.
   - This is a correlation only.

4. **Advisor text leaks into `content`** [observed, code path not found]
   - Re-counted from the baseline JSON: 4/14 runs have "advisor" or "cố vấn" in the first 200 chars of `content` (earlier estimate was ~5). Examples: "Nhận xét từ cố vấn...", "Advisor đồng thuận...".
   - The count is a keyword match, not a manual review of each run.

5. **Persona identity** [observed]
   - persona-nutri R2 self-identifies as "nanobot, trợ lý AI"; Persona identity scored 1.5.
   - Medical safety scored 5.0.

6. **Token figures unreconciled** [unknown]
   - nutritech 1.84M vs 109k; crm 1.13M. No root cause established.

7. **Unknown: artifact location**
   - Specialist artifacts go to `rooms_dir(workspace)/<room_id>/artifacts/<agent>` (`workspace/.coworker/rooms`; `nanobot/coworker/room/store.py:31`, `agents/runtime.py:169`).
   - `rooms_dir(workspace)` = `workspace / ".coworker" / "rooms"` (confirmed).
   - `.nanobot/` in the repo holds only `tool-results`, no `rooms/` or artifacts. The eval workspace location is still unknown; offline re-judging has not been checked.

## Other
- WebView2 perf metrics (6) are deferred: `desktop-perf-baseline.json`, all null.
- `bun run test` fails (exit 1): missing zh-CN keys and a happy-dom ESM error in `copilot-device-login.test.tsx`. Unrelated to `perf.ts`.

## Pending user decisions
- Accept the Phase 0 gate with the WebView2 metrics deferred (Phase 1 code must not start until accepted).
- Choose: option 0 (locate artifacts, re-judge offline), option 1 (fix the harness, then re-run), option 2 (investigate advisor leakage and tokens first).

## Proposed fix order
1. Collect specialist outputs for the judge.
2. Isolate the judge: JSON-only output and a `judge_error` field instead of a 3.0 default.
3. Completion-based waiting instead of the 90s window.
4. Investigate advisor leakage.
5. Reconcile tokens per run.
6. Re-run with at least 3 runs per scenario.

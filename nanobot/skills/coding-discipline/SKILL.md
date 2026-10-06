---
name: coding-discipline
description: Use when fixing a bug or failing test, implementing behavior that tests can cover, handling review feedback, or before saying work is done/fixed/passing. Root cause before fix, test first when practical, evidence before claims. Skip for trivial edits, exploration and throwaway prototypes.
---

# Coding discipline

Condensed from obra/superpowers (MIT): systematic-debugging, verification-before-completion,
test-driven-development, receiving-code-review. Process aids, not rituals: skip them for
typo/rename/config edits and for exploratory spikes.

## 1. Bug or failing test: root cause before fix
1. Read the whole error and stack trace. Reproduce it; if you cannot, gather more data instead of guessing.
2. Check what changed (`git diff`, recent commits, deps, config, environment).
3. Trace backward from the symptom to where the bad value or state originates. Fix at the source.
   Several components (API -> service -> DB)? Log what enters and leaves each boundary once, find the layer that breaks, then dig there.
4. Find similar working code and list every difference.
5. State one hypothesis ("X is the cause because Y"), change one thing to test it, re-run. Wrong? New hypothesis; never stack fixes.
6. Write a failing test (or the smallest repro script) before the fix, then make a single fix. No "while I'm here" cleanups.
7. **Two fixes failed on the same bug: stop and call `advisor`** with the evidence. **Three: question the design**
   (shared state, coupling, wrong pattern) and discuss with the user before fix #4.

Red flags: "quick fix now, investigate later", "just try X", several changes per run, "probably X".
Genuinely environmental or timing issues exist, but most "no root cause" is an incomplete investigation.

## 2. Test first, when it fits
- New behavior or bug fix with a test framework: write one minimal test, run it, confirm it fails for the right reason (feature missing, not a typo), write the least code to pass, run again, then refactor on green.
- Assert on real behavior, not on mocks. Mock only what you must, and only after understanding its side effects.
- Test hard to write = interface too coupled; simplify the design rather than mocking everything.
- Code already written before the test? Do not keep it as "reference": reimplement from the test, or at minimum prove the test can fail (revert the fix, see red, restore, see green).
- Exceptions: prototypes, generated code, pure config, spikes. Say so instead of silently skipping.

## 3. Before claiming done, fixed or passing
No success claim without fresh evidence from this turn.
1. Name the command that proves the claim (tests, linter, build, the original repro).
2. Run it in full; read the output and exit code; count failures.
3. Report the real result with the evidence. Failing or unrun? Say exactly that.

| Claim | Needs | Not enough |
|---|---|---|
| Tests pass | test run, 0 failures | earlier run, "should pass" |
| Build ok | build exit 0 | linter passed |
| Bug fixed | original symptom re-run passes | code changed |
| Requirements met | line-by-line checklist | tests green |
| Delegate (`coding_agent`, subagent) finished | `git diff` / `coding_agent action=diff` read by you | its own "success" report |

Avoid "should", "probably", "seems to" and cheerful sign-offs before verifying. Before the final answer on non-trivial work, consult `advisor` once (after saving the result).

## 4. Receiving review feedback (user, reviewer, advisor)
- Read it all, restate each item, then verify against the actual code before changing anything.
- Unclear item? Ask about it before implementing any related item.
- Do not perform agreement ("You're absolutely right!"); act, or push back with technical reasons when the suggestion is wrong for this codebase or breaks existing behavior.
- Implement one item at a time and re-run tests after each.

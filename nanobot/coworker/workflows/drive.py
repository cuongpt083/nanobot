"""Harness-driven workflow execution: one injected ``[auto-workflow:…]`` turn per step.

Event-driven port of AICoworker's workflow-continuation loop. The binding
(session ↔ active run) is persisted in session metadata. When a turn ends, the
coworker hook calls :func:`on_turn_end`: a finished step turn's reply is parsed
for its JSON output and completed through the engine (which enforces schema and
routing); a rejection re-prompts the same step with the exact errors, bounded;
otherwise the next focus step is injected. The model never advances the graph.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from loguru import logger

from nanobot.coworker.config import load_coworker_config
from nanobot.coworker.runtime import session_state
from nanobot.coworker.transcript import as_dict, as_list
from nanobot.coworker.workflows.engine import (
    RunState,
    WorkflowEngineError,
    abort_run,
    check_graph_pin,
    complete_step,
    make_emitter,
    next_focus_step,
    start_run,
)
from nanobot.coworker.workflows.format import Step, Workflow, load_workflow, validate_workflow
from nanobot.coworker.workflows.registry import RunStore, new_run_id, resolve_ref

WORKFLOW_MARKER = "[auto-workflow:"
KIND_WORKFLOW_STEP = "workflow_step"
CRON_TRIGGER = re.compile(r"\[auto-workflow-cron:([^\]]+)\]\s*([\s\S]*)$")
_JSON_FENCE = re.compile(r"```json\s*([\s\S]*?)```")
_ANY_FENCE = re.compile(r"```[a-z]*\s*([\s\S]*?)```")


@dataclass(frozen=True)
class Injection:
    """A step turn the hook must queue into the session."""

    content: str
    step: str
    run_id: str


# ---------- binding ----------

def binding(session: Any) -> dict[str, Any] | None:
    value = as_dict(session_state(session).get("workflow"))
    return value if value is not None and value.get("run_id") else None


def _clear_binding(session: Any) -> None:
    session_state(session).pop("workflow", None)


def _load(workspace: Path, bound: dict[str, Any]) -> tuple[Workflow, RunState, RunStore]:
    wf = load_workflow(Path(bound["dir"]))
    store = RunStore(workspace, wf.slug, bound["run_id"])
    return wf, store.load(), store


# ---------- public API (tool / commands) ----------

def start(session: Any, workspace: Path, ref: str, run_input: str) -> dict[str, Any]:
    existing = binding(session)
    if existing is not None:
        raise RuntimeError(
            f"run {existing['run_id']} of {existing['ref']} is still active in this session — cancel it first"
        )
    directory = resolve_ref(workspace, ref)
    wf = load_workflow(directory)
    validation = validate_workflow(wf)
    if not validation.ok:
        raise ValueError("workflow is invalid:\n- " + "\n- ".join(validation.errors))
    run, events = start_run(wf, run_id=new_run_id(), run_input=run_input or None)
    RunStore(workspace, wf.slug, run.id).save(run, events)
    session_state(session)["workflow"] = {
        "ref": ref,
        "dir": str(directory),
        "run_id": run.id,
        "pending": True,
        "awaiting": None,
        "retries": 0,
        "rejects": {},
        "turns": 0,
        "human_wait": None,
        "accept_graph_change": False,
    }
    return {"runId": run.id, "workflow": wf.name, "steps": len(wf.steps), "warnings": validation.warnings}


def status(session: Any, workspace: Path) -> dict[str, Any] | None:
    bound = binding(session)
    if bound is None:
        return None
    try:
        wf, run, _ = _load(workspace, bound)
    except Exception as exc:
        return {"ref": bound.get("ref"), "runId": bound.get("run_id"), "error": str(exc)}
    return {
        "ref": bound["ref"],
        "runId": run.id,
        "status": run.status,
        "active": run.active,
        "done": [s for s, st in run.step_state.items() if st.status == "done"],
        "failed": run.failed_steps,
        "steps": len(wf.steps),
        "awaiting": bound.get("awaiting"),
        "waitingForHuman": bound.get("human_wait"),
        "suspended": not bound.get("pending"),
    }


def cancel(session: Any, workspace: Path) -> dict[str, Any]:
    bound = binding(session)
    if bound is None:
        return {"cancelled": False, "reason": "no active run"}
    try:
        _, run, store = _load(workspace, bound)
        if run.status == "running":
            buf, emit = make_emitter(run)
            abort_run(run, emit, "cancelled by user")
            store.save(run, buf)
    except Exception as exc:
        logger.warning("workflow cancel: run {} unreadable: {}", bound.get("run_id"), exc)
    _clear_binding(session)
    return {"cancelled": True, "runId": bound["run_id"]}


def resume(session: Any, *, accept_graph_change: bool = False) -> bool:
    """Re-arm a suspended run; the next turn end injects its focus step."""
    bound = binding(session)
    if bound is None:
        return False
    bound.update({"pending": True, "awaiting": None, "retries": 0, "turns": 0})
    if accept_graph_change:
        bound["accept_graph_change"] = True
    return True


# ---------- prompts ----------

def extract_last_json(text: str | None) -> str | None:
    if not text:
        return None
    blocks = [m.group(1).strip() for m in _JSON_FENCE.finditer(text)]
    if blocks:
        return blocks[-1]
    for m in reversed(list(_ANY_FENCE.finditer(text))):
        candidate = m.group(1).strip()
        if candidate.startswith("{") and _parses(candidate):
            return candidate
    stripped = text.strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        return stripped
    # The LAST top-level parseable {...} embedded in prose ("Result: {...}").
    best: tuple[int, int] | None = None
    start = text.find("{")
    while start >= 0:
        end = _balanced_end(text, start)
        if end is not None and _parses(text[start:end + 1]):
            best = (start, end)
            start = text.find("{", end + 1)
        else:
            start = text.find("{", start + 1)
    return text[best[0]:best[1] + 1] if best else None


def _parses(candidate: str) -> bool:
    try:
        json.loads(candidate)
    except ValueError:
        return False
    return True


def _balanced_end(text: str, start: int) -> int | None:
    depth, in_str, i = 0, False, start
    while i < len(text):
        ch = text[i]
        if in_str:
            if ch == "\\":
                i += 1
            elif ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return None


def example_from_schema(schema: dict[str, Any] | None) -> str | None:
    if schema is None or schema.get("type") != "object":
        return None
    props = as_dict(schema.get("properties")) or {}
    keys = [str(k) for k in as_list(schema.get("required")) or list(props)]
    example: dict[str, Any] = {}
    for key in keys:
        prop = as_dict(props.get(key)) or {}
        options = as_list(prop.get("enum"))
        if options:
            example[key] = "<one of: " + " | ".join(str(e) for e in options) + ">"
        elif prop.get("type") in ("integer", "number"):
            example[key] = 0
        elif prop.get("type") == "boolean":
            example[key] = True
        elif prop.get("type") == "array":
            example[key] = []
        else:
            example[key] = "<real value>"
    return json.dumps(example, ensure_ascii=False)


def step_prompt(wf: Workflow, step: Step, run: RunState, ref: str, *, retry_errors: str | None = None,
                human_answered: bool = False) -> str:
    lines = [
        f"{WORKFLOW_MARKER}{wf.slug}:{step.slug}] WORKFLOW STEP — do exactly this one step now.",
        f'Workflow: {wf.name} ({ref}) · run {run.id} · step "{step.title}" [{step.type}]',
    ]
    if run.input:
        lines.append(f"Run input: {run.input}")
    if retry_errors:
        lines += ["", "YOUR PREVIOUS OUTPUT WAS REJECTED by the engine. Fix EXACTLY these problems:", retry_errors]
    lines += ["", "━━━ STEP INSTRUCTIONS ━━━", step.body.strip(), "━━━━━━━━━━━━━━━━━━━━━━━", ""]
    if step.type == "human":
        if human_answered:
            lines += ["The user has replied above. Report their answer in the output block below.", ""]
        else:
            lines += [
                "This is a HUMAN step: ask the user the question above in plain text and END your turn. "
                "Do NOT emit an output block until the user has answered — the run pauses until they reply.",
                "",
            ]
    if len(step.next) > 1:
        lines.append('ALLOWED ROUTES (you MUST pick exactly one as "route"):')
        lines += [f"  → {e.to}{f'  — when: {e.when}' if e.when else ''}" for e in step.next]
        lines.append("")
    if step.output_schema:
        schema_line = f"matching this JSON-Schema exactly:\n{json.dumps(step.output_schema, ensure_ascii=False)}"
    elif len(step.next) > 1:
        schema_line = 'with at least {"route":"<one of the allowed routes>","reason":"<specific reason>"}'
    else:
        schema_line = "summarizing the step result (any JSON object)"
    lines.append(f"WHEN THE STEP WORK IS DONE, end your reply with EXACTLY ONE fenced ```json code block {schema_line}")
    example = example_from_schema(step.output_schema)
    if example:
        lines += ["", "COPY THIS FORMAT (replace values with the real ones):", "```json", example, "```"]
    lines.append(
        "Do the actual work with real tools first — the JSON block only REPORTS the result. Do not simulate "
        "or skip work. Do not complete any other step. Finish the step WITHIN THIS TURN."
    )
    return "\n".join(lines)


# ---------- drive ----------

def on_turn_end(
    session: Any,
    workspace: Path,
    *,
    final_content: str | None,
    step_turn: tuple[str, str] | None,
    genuine_user_text: str | None,
) -> tuple[Injection | None, str | None]:
    """Advance the bound run after a turn. Returns (step turn to inject, user-facing note)."""
    cfg = load_coworker_config().workflows
    if not cfg.enabled:
        return None, None
    bound = binding(session)
    if bound is None and genuine_user_text:
        trigger = CRON_TRIGGER.search(genuine_user_text.strip())
        if trigger:
            try:
                start(session, workspace, trigger.group(1).strip(), trigger.group(2).strip())
            except Exception as exc:
                return None, f"⚠️ Scheduled workflow {trigger.group(1).strip()} failed to start: {exc}"
            bound = binding(session)
    if bound is None:
        return None, None

    is_step_turn = step_turn is not None and step_turn[0] == bound["run_id"]
    if not is_step_turn:
        if bound.get("human_wait") and genuine_user_text:
            # The user answered a human step: re-ask the model to report the answer.
            bound["awaiting"] = None
            bound["pending"] = True
            return _inject(session, workspace, bound, human_answered=True)
        if not bound.get("pending") or bound.get("awaiting"):
            return None, None  # suspended, or a step turn is already queued
        return _inject(session, workspace, bound)

    assert step_turn is not None
    step_slug = step_turn[1]
    bound["awaiting"] = None
    try:
        wf, run, store = _load(workspace, bound)
    except Exception as exc:
        _clear_binding(session)
        return None, f"⚠️ Workflow run {bound['run_id']} is unreadable and was dropped: {exc}"
    if run.status != "running":
        return _finish(session, bound, run)
    step = wf.steps.get(step_slug)
    output = extract_last_json(final_content)
    if step is not None and step.type == "human" and output is None:
        bound["human_wait"] = step_slug
        bound["pending"] = False
        return None, None
    bound["human_wait"] = None
    buf, emit = make_emitter(run)
    try:
        check_graph_pin(wf, run, emit, accept_change=bool(bound.get("accept_graph_change")))
        complete_step(wf, run, step_slug, emit, output=output)
        bound["accept_graph_change"] = False
        bound["retries"] = 0
        store.save(run, buf)
    except WorkflowEngineError as exc:
        store.trace([{"ev": "step_rejected", "step": step_slug, "code": exc.code, "error": str(exc)[:600]}])
        if exc.code == "graph_changed":
            bound["pending"] = False
            return None, f"⏸️ Workflow paused: {exc}"
        bound["retries"] = int(bound.get("retries", 0)) + 1
        if bound["retries"] <= cfg.step_max_retries:
            return _inject(session, workspace, bound, retry_errors=str(exc))
        # Deterministic failure instead of an endless re-prompt loop.
        buf, emit = make_emitter(run)
        complete_step(wf, run, step_slug, emit, fail=True, note=f"engine rejected output: {exc}")
        store.save(run, buf)
        bound["retries"] = 0
    if run.status != "running":
        return _finish(session, bound, run)
    return _inject(session, workspace, bound)


def _inject(
    session: Any,
    workspace: Path,
    bound: dict[str, Any],
    *,
    retry_errors: str | None = None,
    human_answered: bool = False,
) -> tuple[Injection | None, str | None]:
    cfg = load_coworker_config().workflows
    wf, run, _ = _load(workspace, bound)
    if run.status != "running":
        return _finish(session, bound, run)
    slug = next_focus_step(wf, run)
    if slug is None:
        bound["pending"] = False
        return None, f"⏸️ Workflow {bound['ref']} is stuck (only waiting joins: {', '.join(run.active)}) — suspended."
    bound["turns"] = int(bound.get("turns", 0)) + 1
    if bound["turns"] > cfg.max_step_turns:
        bound["pending"] = False
        return None, f"⏸️ Workflow {bound['ref']} hit {cfg.max_step_turns} step turns — suspended (/workflow resume)."
    bound["awaiting"] = slug
    content = step_prompt(wf, wf.steps[slug], run, bound["ref"], retry_errors=retry_errors,
                          human_answered=human_answered)
    return Injection(content=content, step=slug, run_id=run.id), None


def _finish(session: Any, bound: dict[str, Any], run: RunState) -> tuple[None, str]:
    _clear_binding(session)
    if run.status == "done":
        failed = f" (failed branches: {', '.join(run.failed_steps)})" if run.failed_steps else ""
        return None, f"✅ Workflow {bound['ref']} finished — run {run.id}{failed}."
    return None, f"❌ Workflow {bound['ref']} failed — run {run.id} (failed steps: {', '.join(run.failed_steps) or 'n/a'})."

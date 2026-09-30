"""Deterministic workflow run engine (Python port of AICoworker's graph-workflow v2).

Scripts own state, routing legality, join convergence, budgets and the trace;
the LLM owns judgment only (doing step work, picking decision routes). Errors
are raised BEFORE any state mutation, so a caught error leaves the run reusable.
Error messages are shown to the model verbatim — they are part of the contract.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

from nanobot.coworker.transcript import as_dict, as_list
from nanobot.coworker.workflows.format import (
    Workflow,
    can_reach,
    graph_fingerprint,
    validate_against_schema,
)


class WorkflowEngineError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class StepState:
    attempts: int = 0
    status: str = "queued"  # queued | focus | waiting | done | failed | cancelled
    started_at: str | None = None
    ended_at: str | None = None
    duration_ms: int = 0
    outputs: list[dict[str, Any]] = field(default_factory=list)
    arrived: list[str] = field(default_factory=list)
    arrived_this_fire: list[str] = field(default_factory=list)


@dataclass
class RunState:
    id: str
    workflow: str
    status: str  # running | done | failed
    started: str
    ended: str | None
    input: str | None
    active: list[str]
    step_state: dict[str, StepState]
    failed_steps: list[str]
    event_count: int
    graph_hash: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RunState:
        """Parse a persisted ``run.json`` record (untrusted: validated field by field)."""
        steps: dict[str, StepState] = {}
        for slug, raw in (as_dict(data.get("step_state")) or {}).items():
            st = as_dict(raw) or {}
            steps[slug] = StepState(
                attempts=int(st.get("attempts") or 0),
                status=str(st.get("status") or "queued"),
                started_at=_opt_str(st.get("started_at")),
                ended_at=_opt_str(st.get("ended_at")),
                duration_ms=int(st.get("duration_ms") or 0),
                outputs=[o for item in as_list(st.get("outputs")) or [] if (o := as_dict(item)) is not None],
                arrived=_str_list(st.get("arrived")),
                arrived_this_fire=_str_list(st.get("arrived_this_fire")),
            )
        return cls(
            id=str(data["id"]),
            workflow=str(data["workflow"]),
            status=str(data["status"]),
            started=str(data["started"]),
            ended=_opt_str(data.get("ended")),
            input=_opt_str(data.get("input")),
            active=_str_list(data.get("active")),
            step_state=steps,
            failed_steps=_str_list(data.get("failed_steps")),
            event_count=int(data.get("event_count") or 0),
            graph_hash=str(data.get("graph_hash") or ""),
        )


def _opt_str(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _str_list(value: object) -> list[str]:
    return [item for item in as_list(value) or [] if isinstance(item, str)]


Emit = Callable[[dict[str, Any]], None]


def make_emitter(run: RunState) -> tuple[list[dict[str, Any]], Emit]:
    buf: list[dict[str, Any]] = []

    def emit(event: dict[str, Any]) -> None:
        buf.append({"ts": _now(), **event})
        run.event_count += 1

    return buf, emit


def join_blockers(wf: Workflow, run: RunState, join: str) -> list[str]:
    """A join is blocked while any OTHER active step can still reach it."""
    return [a for a in run.active if a != join and can_reach(wf, a, join)]


def abort_run(run: RunState, emit: Emit, why: str) -> None:
    for slug in run.active:
        st = run.step_state.get(slug)
        if st and st.status in ("focus", "waiting"):
            st.status = "cancelled"
            emit({"ev": "step_cancelled", "step": slug, "reason": why})
    run.active = []
    run.status = "failed"
    run.ended = _now()
    emit({"ev": "run_failed", "reason": why, "failedSteps": run.failed_steps})


def _fire(wf: Workflow, run: RunState, slug: str, source: str | None, emit: Emit) -> bool:
    step = wf.steps[slug]
    st = run.step_state[slug]
    if st.attempts + 1 > step.max_attempts:
        emit({"ev": "budget_exceeded", "step": slug, "maxAttempts": step.max_attempts})
        abort_run(run, emit, f"step {slug} exceeded max_attempts={step.max_attempts} (loop did not converge)")
        return False
    st.status = "focus"
    st.started_at = _now()
    st.attempts += 1
    if step.type == "join":
        st.arrived_this_fire = list(st.arrived)
        st.arrived = []
    if slug not in run.active:
        run.active.append(slug)
    emit({"ev": "step_activated", "step": slug, "type": step.type, "from": source, "attempt": st.attempts})
    return True


def activate(wf: Workflow, run: RunState, slug: str, source: str | None, emit: Emit) -> None:
    step = wf.steps.get(slug)
    if step is None:
        raise WorkflowEngineError("bad_step", f"step {slug} does not exist")
    st = run.step_state.setdefault(slug, StepState())
    if step.type == "join":
        if source and source not in st.arrived:
            st.arrived.append(source)
        emit({"ev": "join_arrival", "step": slug, "from": source})
        if slug not in run.active:
            run.active.append(slug)
        if join_blockers(wf, run, slug):
            st.status = "waiting"
            return
    _fire(wf, run, slug, source, emit)


def reeval_joins(wf: Workflow, run: RunState, emit: Emit, source: str | None) -> None:
    changed = True
    while changed and run.status == "running":
        changed = False
        for slug in sorted(run.active):
            st = run.step_state.get(slug)
            if (
                wf.steps.get(slug) is not None
                and wf.steps[slug].type == "join"
                and st is not None
                and st.status == "waiting"
                and not join_blockers(wf, run, slug)
            ):
                if not _fire(wf, run, slug, source, emit):
                    return
                changed = True


def maybe_finish(wf: Workflow, run: RunState, emit: Emit) -> None:
    if run.status != "running":
        return
    if run.event_count > wf.max_events:
        abort_run(run, emit, f"run exceeded max_events={wf.max_events}")
        return
    if not run.active:
        run.status = "done"
        run.ended = _now()
        emit({"ev": "run_finished", "failedSteps": run.failed_steps})


def complete_step(
    wf: Workflow,
    run: RunState,
    slug: str,
    emit: Emit,
    *,
    output: str | None = None,
    fail: bool = False,
    goto: str | None = None,
    reason: str | None = None,
    note: str | None = None,
) -> None:
    step = wf.steps.get(slug)
    if step is None:
        raise WorkflowEngineError("bad_step", f"step {slug} does not exist")
    st = run.step_state.get(slug)
    if st is None or slug not in run.active:
        active = ", ".join(run.active) or "none"
        raise WorkflowEngineError("not_active", f"step {slug} is not active in run {run.id} (active: {active})")
    if st.status == "waiting":
        raise WorkflowEngineError(
            "join_waiting",
            f"join {slug} is WAITING for branches to converge (arrived so far: {', '.join(st.arrived) or 'none'}) — "
            f"you cannot complete it yet. Finish the other active steps first: {', '.join(join_blockers(wf, run, slug))}",
        )
    if st.status != "focus":
        raise WorkflowEngineError("not_active", f"step {slug} is not in focus (status: {st.status})")

    parsed: Any = None
    parsed_ok = False
    if output is not None:
        try:
            parsed, parsed_ok = json.loads(output), True
        except ValueError:
            parsed = str(output)
    # Failing a step never requires a schema-valid output: that is the point of fail.
    if step.output_schema and not fail:
        if output is None:
            raise WorkflowEngineError(
                "schema_mismatch",
                f"step {slug} declares an ## Output schema — you MUST report a JSON block matching it:\n"
                f"{json.dumps(step.output_schema, indent=2)}",
            )
        if not parsed_ok:
            raise WorkflowEngineError(
                "schema_mismatch",
                f"step {slug}: the output must be valid JSON matching the ## Output schema (got unparseable text).",
            )
        errs = validate_against_schema(parsed, step.output_schema)
        if errs:
            raise WorkflowEngineError(
                "schema_mismatch",
                f"step {slug}: the output does not match the ## Output schema:\n  - "
                + "\n  - ".join(errs)
                + f"\nSchema: {json.dumps(step.output_schema)}\nFix these exact fields and answer again.",
            )

    routes = step.next
    taken: list[str] = []
    if not fail:
        if step.type == "end" or not routes:
            taken = []
        elif step.type == "parallel":
            taken = [r.to for r in routes]
        elif len(routes) == 1 and not goto:
            taken = [routes[0].to]
        else:
            target: str | None = goto
            obj = as_dict(parsed)
            route_field = obj.get("route") if obj is not None else None
            reason_field = obj.get("reason") if obj is not None else None
            if not target and isinstance(route_field, str):
                target = route_field
            if not reason and isinstance(reason_field, str):
                reason = reason_field
            if not target:
                options = " | ".join(f"{r.to}{f' (when: {r.when})' if r.when else ''}" for r in routes)
                raise WorkflowEngineError(
                    "missing_route",
                    f'step {slug} has {len(routes)} routes — include "route" and "reason" fields in the output '
                    f"JSON.\nRoutes: {options}",
                )
            if all(r.to != target for r in routes):
                raise WorkflowEngineError(
                    "routing_violation",
                    f'ROUTING VIOLATION: {slug} has no edge to "{target}". Allowed: '
                    f"{', '.join(r.to for r in routes)}. You may only follow edges defined in the workflow graph.",
                )
            if step.type == "decision" and not reason:
                raise WorkflowEngineError(
                    "missing_reason", f'decision step {slug} requires a "reason" field in the output JSON'
                )
            taken = [target]

    st.status = "failed" if fail else "done"
    st.ended_at = _now()
    if st.started_at:
        started = datetime.fromisoformat(st.started_at)
        st.duration_ms += int((datetime.fromisoformat(st.ended_at) - started).total_seconds() * 1000)
    if output is not None:
        st.outputs.append({"attempt": st.attempts, "at": st.ended_at, "output": parsed})
    run.active = [a for a in run.active if a != slug]
    emit({
        "ev": "step_failed" if fail else "step_done",
        "step": slug,
        "attempt": st.attempts,
        "durationMs": st.duration_ms,
        "output": output,
        "note": note,
    })

    if fail:
        run.failed_steps.append(slug)
        if step.on_fail == "continue":
            emit({"ev": "branch_abandoned", "step": slug})
            reeval_joins(wf, run, emit, slug)
            maybe_finish(wf, run, emit)
        else:
            abort_run(run, emit, f"step {slug} failed (on_fail: abort)")
        return

    if taken and (step.type == "decision" or (len(routes) > 1 and goto)):
        emit({
            "ev": "route",
            "step": slug,
            "to": taken[0],
            "reason": reason,
            "candidates": [{"to": r.to, "when": r.when} for r in routes],
        })
    for target in taken:
        activate(wf, run, target, slug, emit)
        if run.status != "running":
            return
    reeval_joins(wf, run, emit, slug)
    maybe_finish(wf, run, emit)


def check_graph_pin(wf: Workflow, run: RunState, emit: Emit, *, accept_change: bool = False) -> None:
    current = graph_fingerprint(wf)
    if run.graph_hash and current != run.graph_hash:
        if accept_change:
            emit({"ev": "graph_repinned", "from": run.graph_hash, "to": current})
            run.graph_hash = current
            return
        raise WorkflowEngineError(
            "graph_changed",
            f"GRAPH CHANGED since this run started (pinned {run.graph_hash}, now {current}). The workflow's "
            "steps/edges/schemas were edited mid-run. Finish on the old design (restore the files) or re-pin "
            "with /workflow repin.",
        )


def start_run(wf: Workflow, *, run_id: str, run_input: str | None) -> tuple[RunState, list[dict[str, Any]]]:
    if not wf.start:
        raise WorkflowEngineError("bad_step", "workflow has no start step")
    run = RunState(
        id=run_id,
        workflow=wf.slug,
        status="running",
        started=_now(),
        ended=None,
        input=run_input,
        active=[],
        step_state={},
        failed_steps=[],
        event_count=0,
        graph_hash=graph_fingerprint(wf),
    )
    buf, emit = make_emitter(run)
    emit({"ev": "run_started", "workflow": wf.slug, "input": run_input})
    activate(wf, run, wf.start, None, emit)
    maybe_finish(wf, run, emit)
    return run, buf


def next_focus_step(wf: Workflow, run: RunState) -> str | None:
    """Deterministic pick: the first focus step in sorted order."""
    for slug in sorted(run.active):
        st = run.step_state.get(slug)
        if st is not None and st.status == "focus" and slug in wf.steps:
            return slug
    return None

"""Session-level coworker status projection for WebUI inspection."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from nanobot.coworker.advisor import state as advisor_state
from nanobot.coworker.advisor.consult import active_consult, breaker_open_seconds
from nanobot.coworker.coding.project import (
    ProjectError,
    direct_allowed,
    init_preview,
    pending_direct,
    session_project_path,
)
from nanobot.coworker.coding.tasks import CodingTask, shared_registry
from nanobot.coworker.config import CoworkerConfig, load_coworker_config
from nanobot.coworker.context import keepalive, metrics, optimizer
from nanobot.coworker.persona import resolve_persona
from nanobot.coworker.room.scheduler import room_snapshot
from nanobot.coworker.room.store import RoomStateStore, room_id_for
from nanobot.coworker.room.tools import room_armed_for
from nanobot.coworker.runtime import services, session_state, turn_running_since
from nanobot.coworker.transcript import as_dict
from nanobot.session.manager import Session

# Participant states: idle | queued | working | waiting | done | error | paused
ACTIVE_TASK_STATUSES = ("started", "running")
RECENT_FINISHED_TASKS = 3
_TASK_STATE = {
    "started": "working",
    "running": "working",
    "succeeded": "done",
    "failed_acceptance": "error",
    "timed_out": "error",
    "error": "error",
    "aborted": "paused",
    "interrupted": "paused",
}
_OUTCOME_STATE = {"done": "done", "error": "error", "timeout": "error"}


def _participant(
    pid: str,
    kind: str,
    label: str,
    engine: str,
    state: str,
    *,
    task: str | None = None,
    since: float | None = None,
    detail: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "id": pid,
        "kind": kind,
        "label": label,
        "engine": engine,
        "state": state,
        "task": task,
        "since": since,
        "detail": detail or {},
    }


def _task_summary(task: CodingTask) -> dict[str, Any]:
    return {
        "id": task.id,
        "backend": task.backend,
        "status": task.status,
        "brief": task.brief,
        "branch": task.branch,
        "mode": task.mode,
        "changes": {k: list(v) for k, v in task.changes.items()},
        "diffstat": task.diffstat,
        "created_at": task.created_at,
        "updated_at": task.updated_at,
        "live": dict(task.live),
    }


def _session_tasks(ws_root: Path, key: str) -> list[CodingTask]:
    """This session's tasks: in-flight first, then the most recent."""
    mine = [t for t in shared_registry(ws_root).list_tasks() if t.session_key == key]
    active = [t for t in mine if t.status in ACTIVE_TASK_STATUSES]
    finished = [t for t in mine if t.status not in ACTIVE_TASK_STATUSES]
    return [*active, *finished][:10]


def _coding_project(session: Session, non_git: str) -> dict[str, Any]:
    """The project directory the coding agent would use, and whether in-place edits are agreed."""
    try:
        path = session_project_path(session)
    except ProjectError:
        path = None
    return {
        "path": str(path) if path is not None else None,
        "non_git": non_git,
        "direct_allowed": bool(path is not None and direct_allowed(session, path)),
        "pending_direct": pending_direct(session),
        "init_preview": init_preview(session),
    }


def _coding_participants(tasks: list[CodingTask]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    finished = 0
    for t in tasks:
        is_active = t.status in ACTIVE_TASK_STATUSES
        if not is_active:
            finished += 1
            if finished > RECENT_FINISHED_TASKS:
                continue
        live = t.live
        out.append(_participant(
            t.id,
            "coding",
            f"{t.backend} · {t.id}",
            f"backend:{t.backend}",
            _TASK_STATE.get(t.status, "idle"),
            task=t.brief,
            since=t.created_at,
            detail={
                "status": t.status,
                "tools": int(live.get("tool_count", 0) or 0),
                "last_tool": live.get("last_tool"),
                "rounds": int(live.get("rounds", 1) or 1),
                "last_event_at": live.get("last_event_at"),
                "branch": t.branch,
                "diffstat": t.diffstat,
            },
        ))
    return out


def _teammate_participants(
    cfg: CoworkerConfig, key: str, armed: bool
) -> list[dict[str, Any]]:
    snap = room_snapshot(key)
    active = {g.agent_id: g for g in snap.active}
    queued: dict[str, str] = {}
    for d in snap.queued:
        queued.setdefault(d.agent_id, d.task)
    recent: dict[str, str] = {o.agent_id: o.state for o in snap.recent}
    out: list[dict[str, Any]] = []
    for agent in cfg.room.agents:
        since: float | None = None
        task: str | None = None
        detail: dict[str, Any] | None = None
        if agent.id in active:
            guest = active[agent.id]
            state, task, since = "working", guest.task, guest.started_at
            detail = {"rounds": guest.iteration, "last_tool": guest.last_tool}
        elif agent.id in snap.waiting:
            state, task = "waiting", f"waiting for @{snap.waiting[agent.id]}"
        elif agent.id in queued:
            state, task = "queued", queued[agent.id]
        elif agent.id in recent:
            state = _OUTCOME_STATE.get(recent[agent.id], "idle")
        else:
            state = "idle"
        if not armed and state == "idle":
            continue
        label = f"{agent.emoji + ' ' if agent.emoji else ''}{agent.name or agent.id}"
        engine = f"backend:{agent.backend}" if agent.backend else f"preset:{agent.preset or 'default'}"
        out.append(_participant(
            agent.id, "teammate", label, engine, state, task=task, since=since, detail=detail,
        ))
    return out


def coworker_session_status(session: Session) -> dict[str, Any]:
    """Provide a comprehensive, real-time snapshot of all coworker systems for this session."""
    key = session.key
    cfg = load_coworker_config()
    svc = services()
    ws_root = svc.workspace if svc is not None else Path.cwd()

    # 1. Context Cache & Optimizer
    opt_desc = optimizer.describe(key)
    kw_status = keepalive.status_for(session)
    now = time.time()
    expires_at = kw_status.get("expires_at")
    raw_idle = opt_desc.get("idle_seconds")
    idle_s = float(raw_idle) if isinstance(raw_idle, (int, float)) else None

    # If expires_at is available from keepalive, use it; otherwise fallback to optimizer idle
    if expires_at is not None:
        is_warm = bool(expires_at > now)
        remaining_s = max(0, round(expires_at - now)) if is_warm else 0
        ttl_s = round(float(kw_status.get("ttl_s", optimizer.cache_ttl_seconds(cfg.context.cache_ttl_seconds))))
    else:
        ttl_s = optimizer.cache_ttl_seconds(cfg.context.cache_ttl_seconds)
        is_warm = idle_s is not None and idle_s < ttl_s
        remaining_s = max(0, round(ttl_s - idle_s)) if is_warm and idle_s is not None else 0

    latch, pending, opt_source = optimizer.resolve_latched(
        session,
        cold=not is_warm,
        cfg_optimize=cfg.context.optimize,
        cfg_trim=cfg.context.trim.enabled,
    )
    raw_ctx = session_state(session).get("context")
    ctx_state = as_dict(raw_ctx) or {}
    req_opt = ctx_state.get("optimize")
    target_opt = bool(req_opt if req_opt is not None else cfg.context.optimize)
    original_msgs = int(opt_desc.get("original_messages", 0))
    sent_msgs = int(opt_desc.get("sent_messages", 0))
    saved_msgs = max(0, original_msgs - sent_msgs)

    caching_status: dict[str, Any] = {
        "enabled": bool(target_opt or cfg.context.trim.enabled or kw_status.get("enabled")),
        "is_warm": is_warm,
        "idle_seconds": idle_s,
        "ttl_seconds": ttl_s,
        "remaining_seconds": remaining_s,
        "trimmed_messages": int(opt_desc.get("trimmed_messages", 0)),
        "wasted_tools": int(opt_desc.get("wasted", 0)),
        "dropped_junk": int(opt_desc.get("dropped", 0)),
        "rewritten_messages": int(opt_desc.get("rewritten", 0)),
        "system_frozen": bool(opt_desc.get("system_frozen", False)),
        "sent_messages": sent_msgs,
        "original_messages": original_msgs,
        # What the provider reported back (hit rate, read/write tokens), as opposed to what we sent.
        "usage": metrics.snapshot(key),
        "keepalive": kw_status,
        "optimize": {
            "enabled": target_opt,
            "latched": latch.optimize,
            "pending": pending,
            "source": opt_source,
            "dropped": int(opt_desc.get("dropped", 0)),
            "rewritten": int(opt_desc.get("rewritten", 0)),
            "trimmed": int(opt_desc.get("trimmed_messages", 0)),
            "saved_messages": saved_msgs,
        },
    }

    # 2. Advisor
    adv_eff = advisor_state.effective(session)
    last_consult = advisor_state.last_consult(session)
    if adv_eff is None:
        advisor_status: dict[str, Any] = {
            "enabled": False,
            "preset": None,
            "uses": 0,
            "max_uses": cfg.advisor.max_uses,
            "max_tokens": cfg.advisor.max_tokens,
            "breaker_open_seconds": 0,
            "last_consult": last_consult,
            "mode": advisor_state.current_mode(session),
            "default_preset": cfg.advisor.preset,
            "history": advisor_state.history(session),
            "review_nudge": advisor_state.review_nudge(session),
        }
    else:
        advisor_status = {
            "enabled": True,
            "preset": adv_eff.preset,
            "uses": adv_eff.uses,
            "max_uses": adv_eff.max_uses,
            "max_tokens": adv_eff.max_tokens,
            "breaker_open_seconds": round(breaker_open_seconds(adv_eff.preset)),
            "last_consult": last_consult,
            "mode": adv_eff.mode,
            "default_preset": cfg.advisor.preset,
            "history": advisor_state.history(session),
            "review_nudge": advisor_state.review_nudge(session),
        }

    # 3. Room & Teammates
    armed = room_armed_for(session)
    room_entries: list[dict[str, Any]] = []
    if svc is not None and armed:
        try:
            store = RoomStateStore(svc.workspace, room_id_for(key))
            room_entries = store.list()
        except Exception:
            pass

    agent_names = [a.id for a in cfg.room.agents]
    room_status: dict[str, Any] = {
        "enabled": bool(cfg.room.agents),
        "armed": armed,
        "agents": agent_names,
        "state_entries": room_entries,
    }

    # 4. Coding Agent Tasks
    tasks: list[CodingTask] = []
    if cfg.coding.enabled:
        try:
            tasks = _session_tasks(ws_root, key)
        except Exception:
            tasks = []

    # 5. Participants: who is taking part in this session's work right now.
    running_since = turn_running_since(key)
    persona_agent = resolve_persona(session, cfg)
    coordinator_label = (
        f"{persona_agent.emoji} {persona_agent.name or persona_agent.id}".strip()
        if persona_agent and persona_agent.emoji
        else (persona_agent.name or persona_agent.id if persona_agent else "Coordinator")
    )
    coordinator_engine = f"preset:{persona_agent.preset}" if persona_agent and persona_agent.preset else "session"
    participants: list[dict[str, Any]] = [
        _participant(
            "coordinator",
            "coordinator",
            coordinator_label,
            coordinator_engine,
            "working" if running_since is not None else "idle",
            since=running_since,
        )
    ]
    if adv_eff is not None:
        consult = active_consult(key)
        breaker = round(breaker_open_seconds(adv_eff.preset))
        state = "working" if consult is not None else ("paused" if breaker > 0 else "idle")
        participants.append(_participant(
            "advisor",
            "advisor",
            "Advisor",
            f"preset:{adv_eff.preset}",
            state,
            task=consult.focus if consult is not None else None,
            since=consult.started_at if consult is not None else None,
            detail={
                "uses": adv_eff.uses,
                "max_uses": adv_eff.max_uses,
                "breaker_open_seconds": breaker,
                "last_consult": last_consult,
            },
        ))
    participants += _teammate_participants(cfg, key, armed)
    participants += _coding_participants(tasks)

    # 6. Names the composer can offer after "@": what each one does when mentioned.
    room_ids = {a.id for a in cfg.room.agents}
    mentions: list[dict[str, Any]] = [
        {"id": a.id, "kind": "teammate", "label": a.name or a.id, "detail": a.bio}
        for a in cfg.room.agents
    ]
    for backend in ("pi", "agy"):
        if backend not in room_ids:
            mentions.append({
                "id": backend,
                "kind": "coding",
                "label": backend,
                "detail": "coding agent" if cfg.coding.enabled else "coding agent (disabled in settings)",
                "enabled": cfg.coding.enabled,
            })
    if "advisor" not in room_ids:
        mentions.append({
            "id": "advisor",
            "kind": "advisor",
            "label": "advisor",
            "detail": "second opinion" if adv_eff is not None else "second opinion (switched off)",
            "enabled": adv_eff is not None,
        })

    persona_info = {
        "id": persona_agent.id,
        "name": persona_agent.name or persona_agent.id,
        "emoji": persona_agent.emoji,
        "bio": persona_agent.bio,
        "preset": persona_agent.preset,
    } if persona_agent is not None else None

    personas_list = [
        {
            "id": a.id,
            "name": a.name or a.id,
            "emoji": a.emoji,
            "bio": a.bio,
            "preset": a.preset,
        }
        for a in cfg.room.agents
    ]

    return {
        "caching": caching_status,
        "advisor": advisor_status,
        "room": room_status,
        "coding": {
            "enabled": cfg.coding.enabled,
            "tasks": [_task_summary(t) for t in tasks],
            "project": _coding_project(session, cfg.coding.non_git),
        },
        "persona": persona_info,
        "personas": personas_list,
        "participants": participants,
        "mentions": mentions,
        "generated_at": time.time(),
    }

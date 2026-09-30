"""Session-level coworker status projection for WebUI inspection."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from nanobot.coworker.advisor import state as advisor_state
from nanobot.coworker.advisor.consult import breaker_open_seconds
from nanobot.coworker.coding.tasks import TaskRegistry
from nanobot.coworker.config import load_coworker_config
from nanobot.coworker.context import optimizer
from nanobot.coworker.room.store import RoomStateStore, room_id_for
from nanobot.coworker.room.tools import room_armed_for
from nanobot.coworker.runtime import services
from nanobot.session.manager import Session


def coworker_session_status(session: Session) -> dict[str, Any]:
    """Provide a comprehensive, real-time snapshot of all coworker systems for this session."""
    key = session.key
    cfg = load_coworker_config()
    svc = services()
    ws_root = svc.workspace if svc is not None else Path.cwd()

    # 1. Context Cache & Optimizer
    opt_desc = optimizer.describe(key)
    ttl_s = optimizer.cache_ttl_seconds(cfg.context.cache_ttl_seconds)
    raw_idle = opt_desc.get("idle_seconds")
    idle_s = float(raw_idle) if isinstance(raw_idle, (int, float)) else None
    is_warm = idle_s is not None and idle_s < ttl_s
    remaining_s = max(0, round(ttl_s - idle_s)) if is_warm and idle_s is not None else 0

    caching_status: dict[str, Any] = {
        "enabled": bool(cfg.context.optimize or cfg.context.trim.enabled),
        "is_warm": is_warm,
        "idle_seconds": idle_s,
        "ttl_seconds": ttl_s,
        "remaining_seconds": remaining_s,
        "trimmed_messages": int(opt_desc.get("trimmed_messages", 0)),
        "wasted_tools": int(opt_desc.get("wasted", 0)),
        "dropped_junk": int(opt_desc.get("dropped", 0)),
        "rewritten_messages": int(opt_desc.get("rewritten", 0)),
        "system_frozen": bool(opt_desc.get("system_frozen", False)),
        "sent_messages": int(opt_desc.get("sent_messages", 0)),
        "original_messages": int(opt_desc.get("original_messages", 0)),
    }

    # 2. Advisor
    adv_eff = advisor_state.effective(session)
    if adv_eff is None:
        advisor_status: dict[str, Any] = {
            "enabled": False,
            "preset": None,
            "uses": 0,
            "max_uses": cfg.advisor.max_uses,
            "max_tokens": cfg.advisor.max_tokens,
            "breaker_open_seconds": 0,
        }
    else:
        advisor_status = {
            "enabled": True,
            "preset": adv_eff.preset,
            "uses": adv_eff.uses,
            "max_uses": adv_eff.max_uses,
            "max_tokens": adv_eff.max_tokens,
            "breaker_open_seconds": round(breaker_open_seconds(adv_eff.preset)),
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
    tasks_list: list[dict[str, Any]] = []
    if cfg.coding.enabled:
        try:
            registry = TaskRegistry(ws_root)
            all_tasks = registry.list_tasks()
            for t in all_tasks:
                if t.session_key == key or len(tasks_list) < 5:
                    tasks_list.append({
                        "id": t.id,
                        "backend": t.backend,
                        "status": t.status,
                        "brief": t.brief,
                        "branch": t.branch,
                        "diffstat": t.diffstat,
                        "created_at": t.created_at,
                        "updated_at": t.updated_at,
                    })
        except Exception:
            pass

    return {
        "caching": caching_status,
        "advisor": advisor_status,
        "room": room_status,
        "coding": {
            "enabled": cfg.coding.enabled,
            "tasks": tasks_list[:10],
        },
    }

"""Session-level coworker state mutation API."""

from __future__ import annotations

from typing import Any

from nanobot.coworker.advisor import state as advisor_state
from nanobot.coworker.coding.init_repo import InitError, plan_init, run_init
from nanobot.coworker.coding.project import (
    ProjectError,
    clear_init_preview,
    clear_pending_direct,
    grant_direct,
    init_preview,
    path_key,
    revoke_direct,
    session_project_path,
    set_init_preview,
)
from nanobot.coworker.config import load_coworker_config
from nanobot.coworker.context import keepalive, keepalive_state
from nanobot.coworker.persona import set_persona_id
from nanobot.coworker.runtime import session_state
from nanobot.session.manager import Session


class SessionApiError(Exception):
    """Domain error with HTTP status code for coworker session API routes."""

    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


def apply_advisor(session: Session, payload: dict[str, Any]) -> None:
    """Apply advisor switch, model, mode, or budget reset."""
    enabled = payload.get("enabled")
    preset = payload.get("preset")
    mode = payload.get("mode")
    reset_uses = payload.get("reset_uses")

    if enabled is not None and not isinstance(enabled, bool):
        raise SessionApiError("enabled must be a boolean", 400)
    if preset is not None and not isinstance(preset, str):
        raise SessionApiError("preset must be a string", 400)
    if mode is not None and not isinstance(mode, str):
        raise SessionApiError("mode must be a string", 400)
    if reset_uses is not None and not isinstance(reset_uses, bool):
        raise SessionApiError("reset_uses must be a boolean", 400)

    clean_preset = (preset or "").strip() if preset is not None else None
    if clean_preset and clean_preset.lower() == "default":
        advisor_state.set_preset(session, None)
        clean_preset = None

    try:
        if any(k in payload for k in ("enabled", "preset", "mode")):
            advisor_state.apply_switch(
                session,
                enabled=enabled,
                preset=clean_preset,
                mode=mode,
            )
    except ValueError as exc:
        raise SessionApiError(str(exc), 400) from exc

    if reset_uses:
        advisor_state.reset_uses(session)


def apply_keepalive(session: Session, payload: dict[str, Any]) -> None:
    """Apply keep-warm prompt-cache settings."""
    enabled = payload.get("enabled")
    strategy = payload.get("strategy")
    window_min = payload.get("window_min")

    if enabled is not None and not isinstance(enabled, bool):
        raise SessionApiError("enabled must be a boolean or null", 400)
    if strategy is not None:
        if strategy not in ("ping", "ttl1h"):
            raise SessionApiError("strategy must be 'ping' or 'ttl1h'", 400)
        if strategy == "ttl1h":
            st = keepalive.status_for(session)
            if not st.get("ttl1h_supported"):
                raise SessionApiError(
                    "ttl1h strategy is only supported for direct Anthropic provider", 400
                )
    if window_min is not None:
        if not isinstance(window_min, int) or isinstance(window_min, bool):
            raise SessionApiError("window_min must be an integer", 400)

    keepalive_state.apply(
        session,
        enabled=enabled,
        strategy=strategy,
        window_min=window_min,
    )


def apply_context(session: Session, payload: dict[str, Any]) -> None:
    """Apply context optimization or trim overrides."""
    optimize = payload.get("optimize")
    trim = payload.get("trim")

    if optimize is not None and not isinstance(optimize, bool):
        raise SessionApiError("optimize must be a boolean or null", 400)
    if trim is not None and not isinstance(trim, bool):
        raise SessionApiError("trim must be a boolean or null", 400)

    state = session_state(session)
    slot = state.setdefault("context", {})
    if optimize is None:
        slot.pop("optimize", None)
    else:
        slot["optimize"] = optimize
    if trim is None:
        slot.pop("trim", None)
    else:
        slot["trim"] = trim


def apply_persona(session: Session, payload: dict[str, Any]) -> None:
    """Apply per-session persona."""
    cfg = load_coworker_config()
    persona_val = payload.get("persona") or payload.get("id") or payload.get("agent_id")
    if persona_val is not None and not isinstance(persona_val, str):
        raise SessionApiError("persona must be a string or null", 400)
    clean_id = (persona_val or "").strip() if persona_val is not None else None
    if clean_id and clean_id.lower() in ("none", "default"):
        clean_id = None
    try:
        set_persona_id(session, clean_id, cfg)
    except ValueError as exc:
        raise SessionApiError(str(exc), 400) from exc


def apply_coding(session: Session, payload: dict[str, Any]) -> None:
    """Grant or withdraw consent for the coding agent to edit this chat's non-git project in place."""
    direct_ok = payload.get("direct_ok")
    init = payload.get("init")
    path = payload.get("path")
    if init is None and not isinstance(direct_ok, bool):
        raise SessionApiError("direct_ok must be a boolean", 400)
    if init is not None and init not in ("preview", "confirm", "cancel"):
        raise SessionApiError("init must be preview, confirm or cancel", 400)
    if not isinstance(path, str) or not path.strip():
        raise SessionApiError("path must be a non-empty string", 400)
    try:
        project = session_project_path(session)
    except ProjectError as exc:
        raise SessionApiError(str(exc), 400) from exc
    # Consent only ever applies to the directory the user picked for this chat.
    if project is None or path_key(path) != path_key(project):
        raise SessionApiError("path must be this chat's project directory", 400)
    if init is not None:
        try:
            if init == "preview":
                set_init_preview(session, plan_init(project).preview())
            elif init == "cancel":
                clear_init_preview(session)
            else:
                shown = init_preview(session)
                if shown is None or path_key(str(shown.get("path", ""))) != path_key(project):
                    raise InitError("Review the files first, then confirm.")
                run_init(project, str(shown.get("digest", "")))
                clear_init_preview(session)
                clear_pending_direct(session, project)
        except InitError as exc:
            raise SessionApiError(str(exc), 400) from exc
        return
    if direct_ok:
        grant_direct(session, project)
    else:
        revoke_direct(session, project)


SECTIONS = {
    "advisor": apply_advisor,
    "keepalive": apply_keepalive,
    "context": apply_context,
    "persona": apply_persona,
    "coding": apply_coding,
}

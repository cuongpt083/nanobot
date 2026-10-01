"""Per-session persona support using RoomAgentConfig teammates."""

from __future__ import annotations

from typing import Any

from nanobot.coworker.config import CoworkerConfig, RoomAgentConfig
from nanobot.coworker.runtime import session_state
from nanobot.session.model_selection import SESSION_MODEL_PRESET_METADATA_KEY


def get_persona_id(session: Any) -> str | None:
    """Read the current persona agent id for this session, if set."""
    val = session_state(session).get("persona")
    return str(val) if isinstance(val, str) and val.strip() else None


def resolve_persona(session: Any, cfg: CoworkerConfig) -> RoomAgentConfig | None:
    """Look up the RoomAgentConfig matching the session's chosen persona."""
    agent_id = get_persona_id(session)
    if not agent_id:
        return None
    return next((a for a in cfg.room.agents if a.id == agent_id), None)


def set_persona_id(session: Any, agent_id: str | None, cfg: CoworkerConfig) -> RoomAgentConfig | None:
    """Assign or clear the per-session persona.

    When an agent id is set, its configured model preset is also applied to the session's
    model selection metadata so the AgentLoop uses that model.
    """
    state = session_state(session)
    if not agent_id:
        state.pop("persona", None)
        if hasattr(session, "metadata") and isinstance(session.metadata, dict):
            session.metadata.pop(SESSION_MODEL_PRESET_METADATA_KEY, None)
        return None

    agent = next((a for a in cfg.room.agents if a.id == agent_id), None)
    if agent is None:
        raise ValueError(f"unknown persona {agent_id!r}")

    state["persona"] = agent.id
    if hasattr(session, "metadata") and isinstance(session.metadata, dict):
        if agent.preset:
            session.metadata[SESSION_MODEL_PRESET_METADATA_KEY] = agent.preset
        else:
            session.metadata.pop(SESSION_MODEL_PRESET_METADATA_KEY, None)
    return agent

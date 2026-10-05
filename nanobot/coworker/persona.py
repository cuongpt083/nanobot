"""Per-session persona support using RoomAgentConfig teammates."""

from __future__ import annotations

from typing import Any, cast

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


def _metadata(session: Any) -> dict[str, Any] | None:
    meta = getattr(session, "metadata", None)
    return cast("dict[str, Any]", meta) if isinstance(meta, dict) else None


def _prev_persona_preset(state: dict[str, Any], cfg: CoworkerConfig) -> str | None:
    if "persona_preset" in state:
        val = state.get("persona_preset")
        return str(val) if isinstance(val, str) and val.strip() else None
    old_persona = state.get("persona")
    if old_persona:
        old_agent = next((a for a in cfg.room.agents if a.id == old_persona), None)
        if old_agent and old_agent.preset:
            return old_agent.preset
    return None


def set_persona_id(session: Any, agent_id: str | None, cfg: CoworkerConfig) -> RoomAgentConfig | None:
    """Assign or clear the per-session persona.

    When an agent id is set, its configured model preset is also applied to the session's
    model selection metadata so the AgentLoop uses that model.
    """
    state = session_state(session)
    metadata = _metadata(session)
    prev_preset = _prev_persona_preset(state, cfg)

    if not agent_id:
        state.pop("persona", None)
        state.pop("persona_preset", None)
        # Only undo the preset a persona applied; never wipe a model the user picked.
        if metadata is not None and prev_preset:
            if metadata.get(SESSION_MODEL_PRESET_METADATA_KEY) == prev_preset:
                metadata.pop(SESSION_MODEL_PRESET_METADATA_KEY, None)
        return None

    agent = next((a for a in cfg.room.agents if a.id == agent_id), None)
    if agent is None:
        raise ValueError(f"unknown persona {agent_id!r}")

    state["persona"] = agent.id
    if agent.preset:
        state["persona_preset"] = agent.preset
        if metadata is not None:
            metadata[SESSION_MODEL_PRESET_METADATA_KEY] = agent.preset
    else:
        state.pop("persona_preset", None)
        if metadata is not None and prev_preset:
            if metadata.get(SESSION_MODEL_PRESET_METADATA_KEY) == prev_preset:
                metadata.pop(SESSION_MODEL_PRESET_METADATA_KEY, None)
    return agent

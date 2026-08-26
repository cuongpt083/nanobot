"""Zalo-owned persisted login-state detection."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from nanobot.channels.contracts import channel_field_value
from nanobot.config.loader import get_config_path


def resolve_state_dir(section: Any | None = None) -> Path:
    configured = ""
    if section is not None:
        configured = str(
            channel_field_value(section, "stateDir")
            or channel_field_value(section, "state_dir")
            or ""
        ).strip()
    if configured:
        return Path(configured).expanduser()
    return get_config_path().parent / "zalo-auth"


def credentials_path_for(section: Any | None = None) -> Path:
    return resolve_state_dir(section) / "credentials.json"


def local_state_present(section: Any) -> bool:
    path = credentials_path_for(section)
    try:
        raw: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return False
    if not isinstance(raw, dict):
        return False
    payload = dict(cast(dict[str, Any], raw))
    imei = payload.get("imei")
    cookie = payload.get("cookie")
    user_agent = payload.get("userAgent")
    return bool(
        isinstance(imei, str)
        and imei.strip()
        and cookie
        and isinstance(user_agent, str)
        and user_agent.strip()
    )


__all__ = ["credentials_path_for", "local_state_present", "resolve_state_dir"]

"""Compact stable turn identity utilities for pilot mode."""

from __future__ import annotations

import uuid

PILOT_TURN_ID_KEY = "_pilot_turn_id"
CLIENT_TURN_ID_KEY = "client_turn_id"


def new_turn_id() -> str:
    """Generate a 32-character lowercase UUID4 hex string.

    This ID fits within Telegram callback_data limit (64 bytes) even when
    prefixed with 'fb:x:' (37 bytes total). It does not encode channel, chat,
    or user identifiers.
    """
    return uuid.uuid4().hex

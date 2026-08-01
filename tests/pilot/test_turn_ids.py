from __future__ import annotations

import re
from typing import Any

from nanobot.pilot.turns import CLIENT_TURN_ID_KEY, PILOT_TURN_ID_KEY, new_turn_id
from nanobot.session.manager import SessionManager
from nanobot.session.webui_turns import public_history_message


def test_new_turn_id_format_and_uniqueness() -> None:
    ids = [new_turn_id() for _ in range(20)]
    assert len(set(ids)) == 20
    for tid in ids:
        assert isinstance(tid, str)
        assert len(tid) == 32
        assert re.match(r"^[0-9a-f]{32}$", tid)


def test_turn_id_fits_telegram_callback_data_limits() -> None:
    tid = new_turn_id()
    callback_data = f"fb:x:{tid}"
    assert len(callback_data.encode("utf-8")) <= 64


def test_session_manager_lookup_preceding_user_message_by_turn_id(tmp_path: Any) -> None:
    mgr = SessionManager(tmp_path)
    session = mgr.get_or_create("test:chat1")

    tid1 = new_turn_id()
    session.add_message("user", "Hello first", _pilot_turn_id=tid1)
    session.add_message("assistant", "Hi first", _pilot_turn_id=tid1)

    tid2 = new_turn_id()
    session.add_message("user", "Hello second", _pilot_turn_id=tid2)
    session.add_message("assistant", "Hi second", _pilot_turn_id=tid2)
    mgr.save(session)

    found = mgr.get_preceding_user_message("test:chat1", tid2)
    assert found is not None
    assert found["content"] == "Hello second"
    assert found["role"] == "user"


def test_pilot_turn_id_stripped_from_public_history() -> None:
    msg = {
        "role": "assistant",
        "content": "Hello",
        "timestamp": "2026-07-30T12:00:00",
        PILOT_TURN_ID_KEY: new_turn_id(),
        CLIENT_TURN_ID_KEY: "client-123",
    }
    public_msg = public_history_message(msg)
    assert PILOT_TURN_ID_KEY not in public_msg
    assert public_msg.get(CLIENT_TURN_ID_KEY) == "client-123"

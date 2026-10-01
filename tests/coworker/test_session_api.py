"""Tests for coworker session_api module."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from nanobot.coworker import session_api
from nanobot.coworker.advisor import state as advisor_state
from nanobot.coworker.context import keepalive_state
from nanobot.coworker.runtime import session_state
from nanobot.coworker.session_api import SessionApiError


def _session() -> SimpleNamespace:
    return SimpleNamespace(key="s1", messages=[], metadata={})


def test_apply_advisor_validation() -> None:
    session = _session()
    # Invalid enabled
    with pytest.raises(SessionApiError) as exc:
        session_api.apply_advisor(session, {"enabled": "yes"})
    assert exc.value.status == 400

    # Invalid preset
    with pytest.raises(SessionApiError) as exc:
        session_api.apply_advisor(session, {"preset": 123})
    assert exc.value.status == 400

    # Invalid mode
    with pytest.raises(SessionApiError) as exc:
        session_api.apply_advisor(session, {"mode": 123})
    assert exc.value.status == 400


def test_apply_advisor_reset_uses() -> None:
    session = _session()
    slot = session_state(session).setdefault("advisor", {})
    slot["uses"] = 5
    assert advisor_state.effective(session) is None or slot.get("uses") == 5

    session_api.apply_advisor(session, {"reset_uses": True})
    assert slot.get("uses") == 0


def test_apply_keepalive_validation() -> None:
    session = _session()
    # Invalid enabled
    with pytest.raises(SessionApiError) as exc:
        session_api.apply_keepalive(session, {"enabled": "false"})
    assert exc.value.status == 400

    # Invalid strategy
    with pytest.raises(SessionApiError) as exc:
        session_api.apply_keepalive(session, {"strategy": "random"})
    assert exc.value.status == 400

    # Unsupported ttl1h
    with pytest.raises(SessionApiError) as exc:
        session_api.apply_keepalive(session, {"strategy": "ttl1h"})
    assert exc.value.status == 400
    assert "supported" in str(exc.value)

    # Valid apply
    session_api.apply_keepalive(session, {"enabled": True, "strategy": "ping", "window_min": 45})
    eff = keepalive_state.effective(session)
    assert eff.enabled is True
    assert eff.strategy == "ping"
    assert eff.window_min == 45


def test_apply_context() -> None:
    session = _session()
    with pytest.raises(SessionApiError) as exc:
        session_api.apply_context(session, {"optimize": "yes"})
    assert exc.value.status == 400

    session_api.apply_context(session, {"optimize": True, "trim": False})
    state = session_state(session)
    assert state["context"]["optimize"] is True
    assert state["context"]["trim"] is False

    # Clear
    session_api.apply_context(session, {"optimize": None})
    assert "optimize" not in state["context"]

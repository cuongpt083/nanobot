"""Tests for coworker session status projection."""

from nanobot.coworker.status import coworker_session_status
from nanobot.session.manager import Session


def test_coworker_session_status_default() -> None:
    session = Session(key="websocket:test-coworker-123", messages=[])
    status = coworker_session_status(session)

    assert "caching" in status
    assert "advisor" in status
    assert "room" in status
    assert "coding" in status

    assert isinstance(status["caching"]["is_warm"], bool)
    assert isinstance(status["caching"]["ttl_seconds"], float)
    assert isinstance(status["advisor"]["enabled"], bool)
    assert isinstance(status["room"]["armed"], bool)
    assert isinstance(status["coding"]["tasks"], list)

"""Tests for SQLitePilotStore data access methods."""

from nanobot.pilot.store import SQLitePilotStore
from nanobot.pilot.types import CapturePriority, ConsentState, QueueEvent


def make_queue_event(event_id: str, kind: str, payload: dict) -> QueueEvent:
    return QueueEvent(
        event_id=event_id,
        priority=CapturePriority.FINAL,
        kind=kind,
        payload=payload,
        created_at_ms=1000,
    )


def test_write_batch_and_ownership(tmp_path) -> None:
    store = SQLitePilotStore(tmp_path / "store.db")

    turn_event = make_queue_event(
        "turn_1",
        "turn",
        {
            "turn_id": "turn_1",
            "user_pseudonym": "user_hash_1",
            "session_pseudonym": "sess_hash_1",
            "channel": "webui",
            "chat_id": "chat_1",
            "routing_decision": {"primary": "deepseek"},
        },
    )

    written = store.write_batch([turn_event])
    assert written == 1

    ownership = store.get_ownership("turn_1")
    assert ownership == ("user_hash_1", "sess_hash_1")
    assert store.get_ownership("nonexistent") is None
    store.close()


def test_consent_management(tmp_path) -> None:
    store = SQLitePilotStore(tmp_path / "store.db")

    consent = ConsentState(
        user_pseudonym="u1",
        product_allowed=True,
        product_version="v1",
        training_allowed=False,
        training_version="v1",
        created_at_ms=100,
        updated_at_ms=100,
    )
    store.save_consent(consent)

    retrieved = store.get_consent("u1")
    assert retrieved is not None
    assert retrieved.product_allowed is True
    assert retrieved.training_allowed is False

    # Update consent
    updated = ConsentState(
        user_pseudonym="u1",
        product_allowed=True,
        product_version="v1",
        training_allowed=True,
        training_version="v1",
        created_at_ms=100,
        updated_at_ms=200,
    )
    store.save_consent(updated)
    assert store.get_consent("u1").training_allowed is True
    store.close()


def test_deletion_by_pseudonym(tmp_path) -> None:
    store = SQLitePilotStore(tmp_path / "store.db")

    turn_event = make_queue_event(
        "t1",
        "turn",
        {
            "turn_id": "t1",
            "user_pseudonym": "user_del",
            "session_pseudonym": "sess_1",
            "channel": "webui",
            "chat_id": "c1",
        },
    )
    fb_event = make_queue_event(
        "fb1",
        "feedback",
        {
            "turn_id": "t1",
            "user_pseudonym": "user_del",
            "kind": "helpful",
        },
    )

    store.write_batch([turn_event, fb_event])
    assert store.get_turn_count("user_del") == 1

    result = store.delete_by_pseudonym("user_del")
    assert result["turn_count"] == 1
    assert result["feedback_count"] == 1
    assert store.get_turn_count("user_del") == 0
    store.close()

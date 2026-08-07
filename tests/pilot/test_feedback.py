"""Tests for FeedbackService."""

from unittest.mock import AsyncMock

import pytest

from nanobot.bus.events import FeedbackAction
from nanobot.pilot.feedback import FeedbackService
from nanobot.pilot.identity import IdentityHasher
from nanobot.pilot.store import SQLitePilotStore
from nanobot.pilot.types import CapturePriority, QueueEvent


@pytest.mark.asyncio
async def test_feedback_handling_success(tmp_path) -> None:
    store = SQLitePilotStore(tmp_path / "fb.db")
    hasher = IdentityHasher("secret")
    bus_mock = AsyncMock()

    user_pseudo = hasher.hash_identity("user", "webui:usr_1")
    sess_pseudo = hasher.hash_identity("session", "sess_1")

    # Record turn ownership row
    store.write_batch(
        [
            QueueEvent(
                event_id="t1",
                priority=CapturePriority.FINAL,
                kind="turn",
                payload={
                    "turn_id": "turn_123",
                    "user_pseudonym": user_pseudo,
                    "session_pseudonym": sess_pseudo,
                    "channel": "webui",
                    "chat_id": "usr_1",
                },
                created_at_ms=1000,
            )
        ]
    )

    service = FeedbackService(store=store, hasher=hasher, bus=bus_mock)

    action = FeedbackAction(
        action_id="act_1",
        turn_id="turn_123",
        kind="helpful",
        channel="webui",
        sender_id="usr_1",
        chat_id="usr_1",
        session_key="webui:usr_1",
    )

    ack = await service.handle_action(action)
    assert ack.accepted is True
    assert ack.turn_id == "turn_123"

    store.close()


@pytest.mark.asyncio
async def test_feedback_ownership_denial(tmp_path) -> None:
    store = SQLitePilotStore(tmp_path / "fb_deny.db")
    hasher = IdentityHasher("secret")

    owner_pseudo = hasher.hash_identity("user", "webui:alice")
    store.write_batch(
        [
            QueueEvent(
                event_id="t1",
                priority=CapturePriority.FINAL,
                kind="turn",
                payload={
                    "turn_id": "turn_alice",
                    "user_pseudonym": owner_pseudo,
                    "session_pseudonym": "sess_alice",
                    "channel": "webui",
                    "chat_id": "alice",
                },
                created_at_ms=1000,
            )
        ]
    )

    service = FeedbackService(store=store, hasher=hasher)

    # Bob tries to submit feedback for Alice's turn
    action = FeedbackAction(
        action_id="act_bob",
        turn_id="turn_alice",
        kind="helpful",
        channel="webui",
        sender_id="bob",
        chat_id="bob",
        session_key="webui:bob",
    )

    ack = await service.handle_action(action)
    assert ack.accepted is False
    assert ack.reason == "ownership_denied"

    store.close()


@pytest.mark.asyncio
async def test_feedback_retry_triggers_inbound_message(tmp_path) -> None:
    store = SQLitePilotStore(tmp_path / "fb_retry.db")
    hasher = IdentityHasher("secret")
    bus_mock = AsyncMock()

    user_pseudo = hasher.hash_identity("user", "webui:usr_retry")
    store.write_batch(
        [
            QueueEvent(
                event_id="t_retry",
                priority=CapturePriority.FINAL,
                kind="turn",
                payload={
                    "turn_id": "turn_to_retry",
                    "user_pseudonym": user_pseudo,
                    "session_pseudonym": "sess_r",
                    "channel": "webui",
                    "chat_id": "usr_retry",
                },
                created_at_ms=1000,
            )
        ]
    )

    service = FeedbackService(store=store, hasher=hasher, bus=bus_mock)

    action = FeedbackAction(
        action_id="act_retry_1",
        turn_id="turn_to_retry",
        kind="retry",
        channel="webui",
        sender_id="usr_retry",
        chat_id="usr_retry",
        session_key="webui:usr_retry",
    )

    ack = await service.handle_action(action)
    assert ack.accepted is True
    assert bus_mock.publish_inbound.called

    store.close()

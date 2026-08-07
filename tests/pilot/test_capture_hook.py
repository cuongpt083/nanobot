"""Tests for DistillationCaptureHook and exception boundary isolation."""

from unittest.mock import MagicMock

import pytest

from nanobot.agent.hook import AgentRunHookContext, AgentTurnHookContext
from nanobot.pilot.capture import DistillationCaptureHook
from nanobot.pilot.consent import ConsentGate
from nanobot.pilot.identity import IdentityHasher
from nanobot.pilot.queue import CaptureQueue
from nanobot.pilot.redaction import Redactor
from nanobot.pilot.store import SQLitePilotStore
from nanobot.pilot.types import ConsentState


@pytest.mark.asyncio
async def test_hook_process_capture(tmp_path) -> None:
    store = SQLitePilotStore(tmp_path / "test_hook.db")
    hasher = IdentityHasher("secret")
    redactor = Redactor()
    consent_gate = ConsentGate(operator_enabled=True)
    queue = CaptureQueue()

    user_pseudo = hasher.hash_identity("user", "webui:user123")
    store.save_consent(
        ConsentState(
            user_pseudonym=user_pseudo,
            product_allowed=True,
            product_version="v1",
            training_allowed=True,
            training_version="v1",
            created_at_ms=100,
            updated_at_ms=100,
        )
    )

    turn_ctx = AgentTurnHookContext(
        channel="webui",
        chat_id="user123",
        turn_id="turn_abc",
        provider_config={"capture_policy": "reasoning"},
    )

    hook = DistillationCaptureHook(
        turn_context=turn_ctx,
        queue=queue,
        hasher=hasher,
        redactor=redactor,
        consent_gate=consent_gate,
        store=store,
    )

    run_ctx = AgentRunHookContext(
        messages=[{"role": "user", "content": "Hello nanobot!"}],
        final_content="Hello user!",
    )

    await hook.after_run(run_ctx)

    turn_event = await queue.get()
    assert turn_event is not None
    assert turn_event.kind == "turn"
    assert turn_event.payload["turn_id"] == "turn_abc"

    artifact_event = await queue.get()
    assert artifact_event is not None
    assert artifact_event.kind == "artifact"
    assert artifact_event.payload["prompt_text"] == "Hello nanobot!"
    assert artifact_event.payload["answer_text"] == "Hello user!"

    store.close()


@pytest.mark.asyncio
async def test_hook_exception_isolation() -> None:
    # Verify hook errors do not raise or break the turn
    bad_store = MagicMock()
    bad_store.get_consent.side_effect = Exception("DB crash!")

    turn_ctx = AgentTurnHookContext(channel="webui", chat_id="user123")
    hook = DistillationCaptureHook(
        turn_context=turn_ctx,
        queue=CaptureQueue(),
        hasher=IdentityHasher("secret"),
        redactor=Redactor(),
        consent_gate=ConsentGate(operator_enabled=True),
        store=bad_store,
    )

    run_ctx = AgentRunHookContext(messages=[])
    # Should not raise exception
    await hook.after_run(run_ctx)

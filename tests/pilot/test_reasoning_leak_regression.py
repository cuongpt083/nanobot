"""Leak regression tests: assert zero reasoning canaries leak in presentation outputs."""

from nanobot.bus.outbound_events import ProgressEvent
from nanobot.pilot.presentation import PresentationPolicy

CANARY_STRING = "CANARY_THINKING_TOKEN_12345"


def test_presentation_policy_prevents_reasoning_leak() -> None:
    policy = PresentationPolicy()

    # ProgressEvent containing reasoning should be rejected when show_reasoning=False
    event = ProgressEvent(reasoning=f"Internal thoughts {CANARY_STRING}")
    assert policy.permits_event(event, show_reasoning=False) is False

    # Standard message containing think block should have think block stripped
    raw_content = f"<think>Internal reasoning {CANARY_STRING}</think>Public response"
    res = policy.sanitize(raw_content, {})
    assert CANARY_STRING not in res.content
    assert res.content.strip() == "Public response"


def test_presentation_policy_redacts_metadata_keys() -> None:
    policy = PresentationPolicy()
    metadata = {
        "reasoning": f"Secret reasoning {CANARY_STRING}",
        "thinking_blocks": [CANARY_STRING],
        "safe_key": "safe_value",
    }
    res = policy.sanitize("Hello world", metadata)
    assert CANARY_STRING not in str(res.metadata)
    assert "reasoning" not in res.metadata
    assert "thinking_blocks" not in res.metadata
    assert res.metadata["safe_key"] == "safe_value"

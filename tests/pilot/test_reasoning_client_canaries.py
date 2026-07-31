from __future__ import annotations

from typing import Any

from nanobot.bus.outbound_events import ProgressEvent
from nanobot.pilot.presentation import PresentationPolicy


def test_presentation_policy_filters_reasoning_events_when_reasoning_disabled() -> None:
    policy = PresentationPolicy()

    # ProgressEvent with reasoning
    event = ProgressEvent(reasoning="SECRET_REASONING_CANARY_123")
    assert policy.permits_event(event, show_reasoning=False) is False
    assert policy.permits_event(event, show_reasoning=True) is True

    # ProgressEvent with reasoning_delta
    event_delta = ProgressEvent(reasoning_delta="SECRET_DELTA_CANARY_456")
    assert policy.permits_event(event_delta, show_reasoning=False) is False
    assert policy.permits_event(event_delta, show_reasoning=True) is True

    # ProgressEvent with reasoning_end
    event_end = ProgressEvent(reasoning_end=True)
    assert policy.permits_event(event_end, show_reasoning=False) is False
    assert policy.permits_event(event_end, show_reasoning=True) is True


def test_presentation_policy_sanitizes_reasoning_content_and_metadata() -> None:
    policy = PresentationPolicy()

    content = "Answer text with <think>SECRET_THINKING_BLOCK</think> final response."
    metadata: dict[str, Any] = {
        "reasoning_content": "SECRET_REASONING_METADATA",
        "thinking_blocks": ["SECRET_BLOCK"],
        "tool_arguments": {"secret": "val"},
        "normal_key": "safe_val",
    }

    res = policy.sanitize(content, metadata)

    assert "SECRET_THINKING_BLOCK" not in res.content
    assert res.content == "Answer text with  final response."
    assert "reasoning_content" not in res.metadata
    assert "thinking_blocks" not in res.metadata
    assert "tool_arguments" not in res.metadata
    assert res.metadata.get("normal_key") == "safe_val"
    assert res.leak_prevented is True


def test_presentation_policy_redacts_private_keys_and_tokens() -> None:
    policy = PresentationPolicy()

    raw = (
        "Key: sk-1234567890abcdef1234567890\n"
        "Auth: Bearer secret-token-abc\n"
        "PEM: -----BEGIN PRIVATE KEY-----\nsecret_pem_data\n-----END PRIVATE KEY-----\n"
        "Path: C:\\Users\\Admin\\secret.txt and /var/run/secrets/token\n"
    )

    res = policy.sanitize(raw, {})

    assert "sk-1234567890abcdef1234567890" not in res.content
    assert "secret-token-abc" not in res.content
    assert "secret_pem_data" not in res.content
    assert "C:\\Users\\Admin\\secret.txt" not in res.content
    assert "/var/run/secrets/token" not in res.content

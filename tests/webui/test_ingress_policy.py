from __future__ import annotations

from nanobot.webui.ingress_policy import WebUIIngressPolicy


def test_text_limit_counts_utf8_bytes() -> None:
    policy = WebUIIngressPolicy()

    assert policy.validate_text("x" * policy.message.max_text_bytes) is None
    assert policy.validate_text("你" * 22_000) == "text_too_large"


def test_bootstrap_keeps_transport_and_business_limits_separate() -> None:
    policy = WebUIIngressPolicy()

    payload = policy.bootstrap_limits(max_frame_bytes=1_048_576)

    assert payload["transport"] == {
        "max_frame_bytes": 1_048_576,
        "envelope_reserve_bytes": 65_536,
    }
    assert payload["message"] == {"max_text_bytes": 65_536}
    assert payload["attachments"] == {
        "max_count": 4,
        "max_file_bytes": 6_291_456,
        "max_total_bytes": 25_165_824,
    }
    assert policy.minimum_full_policy_frame_bytes() < 36 * 1024 * 1024


def test_websocket_pilot_mode_rejects_wildcard_allow_from() -> None:
    from unittest.mock import MagicMock

    import pytest

    from nanobot.bus.queue import MessageBus
    from nanobot.channels.websocket.runtime import WebSocketChannel, WebSocketConfig

    mock_gateway = MagicMock()
    with pytest.raises(ValueError, match="Wildcard allow_from"):
        WebSocketChannel(
            WebSocketConfig(allow_from=["*"]),
            MessageBus(),
            gateway=mock_gateway,
            pilot_mode=True,
        )


def test_websocket_pilot_mode_enforces_token_requirement() -> None:
    from unittest.mock import MagicMock

    from nanobot.bus.queue import MessageBus
    from nanobot.channels.websocket.runtime import WebSocketChannel, WebSocketConfig

    mock_gateway = MagicMock()
    channel = WebSocketChannel(
        WebSocketConfig(allow_from=["allowed-client"], websocket_requires_token=False),
        MessageBus(),
        gateway=mock_gateway,
        pilot_mode=True,
    )
    assert channel.config.websocket_requires_token is True

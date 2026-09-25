"""Zalo setup validation owned by the channel package."""

from typing import Any

from nanobot.channels.contracts import ChannelValidationContext
from nanobot.channels.validation import check, enabled, official_action, payload, string_value


def validate(values: dict[str, Any], _context: ChannelValidationContext) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    bridge_url = string_value(values.get("bridgeUrl"))
    if enabled(values) or bridge_url:
        checks.append(
            check(
                "bridge_url",
                "Bridge URL",
                "pass",
                f"Zalo WebSocket bridge configured at {bridge_url or 'ws://127.0.0.1:3002'}.",
            )
        )
        return payload("zalo", "configured", checks, can_enable=True)
    checks.append(
        check(
            "bridge_url",
            "Bridge URL",
            "missing",
            "Zalo channel connects to a zca-js WebSocket bridge (default ws://127.0.0.1:3002).",
            action_url=official_action("zalo"),
        )
    )
    return payload(
        "zalo",
        "needs_setup",
        checks,
        missing_fields=["bridgeUrl"],
        can_enable=False,
    )


__all__ = ["validate"]

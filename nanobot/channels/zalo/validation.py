"""Zalo setup validation owned by the channel package."""

from typing import Any

from nanobot.channels.contracts import ChannelValidationContext
from nanobot.channels.validation import check, enabled, official_action, payload, string_value


def validate(values: dict[str, Any], _context: ChannelValidationContext) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    if enabled(values) or string_value(values.get("stateDir")):
        checks.append(
            check(
                "local_state",
                "Local login state",
                "pass",
                "Saved local login state was detected.",
            )
        )
        return payload("zalo", "configured", checks, can_enable=True)
    checks.append(
        check(
            "qr_login",
            "QR login",
            "skipped",
            "This channel uses a QR login flow (Zalo personal account via zca-js).",
            action_url=official_action("zalo"),
        )
    )
    return payload(
        "zalo",
        "needs_setup",
        checks,
        missing_fields=["qr_login"],
        can_enable=False,
    )


__all__ = ["validate"]

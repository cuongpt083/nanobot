"""Init file for pi coding module."""

from pathlib import Path

from nanobot.coworker.coding.pi.client import PiClient
from nanobot.coworker.coding.pi.protocol import Command, Event, Response
from nanobot.coworker.coding.pi.transport import JsonlChannel
from nanobot.coworker.coding.pi.version import check_pi_version, get_pi_version

EXTENSION_PATH = Path(__file__).parent / "extension" / "nanobot-bridge.ts"

__all__ = [
    "Command",
    "EXTENSION_PATH",
    "Event",
    "JsonlChannel",
    "PiClient",
    "Response",
    "check_pi_version",
    "get_pi_version",
]

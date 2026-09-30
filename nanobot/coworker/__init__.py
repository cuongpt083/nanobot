"""Coworker extension — features ported from AICoworker, kept out of the upstream core.

Features: advisor consults, multi-agent rooms (room_delegate / room_state),
cache-aware context trimming + keep-alive, and agent workflows (run / distill).
Wired into nanobot through a handful of documented seams (see docs/coworker/README.md).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nanobot.agent.hook import AgentTurnHookFactory
    from nanobot.command.router import CommandRouter


def hook_factories() -> list[AgentTurnHookFactory]:
    from nanobot.coworker.hook import create_coworker_hook

    return [create_coworker_hook]


def register_commands(router: CommandRouter) -> None:
    from nanobot.coworker.commands import register

    register(router)

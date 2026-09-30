"""Discovery of optional in-process agent extensions.

An extension is a module exposing any of:

- ``hook_factories() -> list[AgentTurnHookFactory]`` — per-turn runner hooks.
- ``register_commands(router: CommandRouter) -> None`` — extra slash commands.

Extensions are the fork-local modules listed in ``_BUILTIN_EXTENSIONS`` plus any
module registered under the ``nanobot.extensions`` entry-point group. A broken
extension is logged and skipped; it never prevents the agent from starting.
"""

from __future__ import annotations

import importlib
from functools import cache
from importlib.metadata import entry_points
from types import ModuleType
from typing import TYPE_CHECKING, cast

from loguru import logger

if TYPE_CHECKING:
    from nanobot.agent.hook import AgentTurnHookFactory
    from nanobot.command.router import CommandRouter

_BUILTIN_EXTENSIONS = ("nanobot.coworker",)


@cache
def _extension_modules() -> tuple[ModuleType, ...]:
    modules: list[ModuleType] = []
    for name in _BUILTIN_EXTENSIONS:
        try:
            modules.append(importlib.import_module(name))
        except ModuleNotFoundError:
            continue
        except Exception:
            logger.exception("Failed to import agent extension {}", name)
    try:
        eps = entry_points(group="nanobot.extensions")
    except Exception:
        eps = ()
    for ep in eps:
        try:
            module = ep.load()
        except Exception:
            logger.exception("Failed to load agent extension {}", ep.name)
            continue
        if isinstance(module, ModuleType):
            modules.append(module)
    return tuple(modules)


def extension_hook_factories() -> list[AgentTurnHookFactory]:
    factories: list[AgentTurnHookFactory] = []
    for module in _extension_modules():
        provider = getattr(module, "hook_factories", None)
        if not callable(provider):
            continue
        try:
            produced: object = provider()
            items = cast("list[object]", produced) if isinstance(produced, list) else []
            # Callability is the only contract a factory list can be checked for at runtime.
            factories.extend(cast("AgentTurnHookFactory", f) for f in items if callable(f))
        except Exception:
            logger.exception("Agent extension {} failed to build hook factories", module.__name__)
    return factories


def register_extension_commands(router: CommandRouter) -> None:
    for module in _extension_modules():
        register = getattr(module, "register_commands", None)
        if not callable(register):
            continue
        try:
            register(router)
        except Exception:
            logger.exception("Agent extension {} failed to register commands", module.__name__)

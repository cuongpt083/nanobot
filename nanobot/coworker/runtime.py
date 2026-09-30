"""Process-wide services shared by coworker tools, hooks and commands.

Tools receive the agent loop's ``ToolContext`` at registration; the first main
scope coworker tool binds those services here so hooks and background tasks
(room turns, workflow drive, keep-alive) can reach the bus, the session store
and model presets without any extra wiring in the core loop.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.coworker.transcript import as_dict

if TYPE_CHECKING:
    from nanobot.agent.subagent import SubagentManager
    from nanobot.agent.tools.context import ToolContext
    from nanobot.bus.queue import MessageBus
    from nanobot.providers.factory import ProviderSnapshot
    from nanobot.session.manager import Session, SessionManager
    from nanobot.utils.llm_runtime import LLMRuntime

COWORKER_META = "coworker"
INJECTED_EVENT = "coworker"
KIND_META = "coworker_kind"


@dataclass
class CoworkerServices:
    workspace: Path
    bus: MessageBus
    sessions: SessionManager
    subagents: SubagentManager | None
    provider_snapshot_loader: Callable[..., ProviderSnapshot] | None


_services: CoworkerServices | None = None
_live_messages: dict[str, list[dict[str, Any]]] = {}
_background: set[asyncio.Task[Any]] = set()


def bind_services(ctx: ToolContext) -> None:
    """Capture main-loop services; subagent tool contexts lack them and are ignored."""
    global _services
    if ctx.bus is None or ctx.sessions is None:
        return
    _services = CoworkerServices(
        workspace=Path(ctx.workspace).expanduser().resolve(),
        bus=ctx.bus,
        sessions=ctx.sessions,
        subagents=ctx.subagent_manager,
        provider_snapshot_loader=ctx.provider_snapshot_loader,
    )


def services() -> CoworkerServices | None:
    return _services


def set_services(value: CoworkerServices | None) -> None:
    global _services
    _services = value


def remember_live_messages(session_key: str | None, messages: list[dict[str, Any]]) -> None:
    """Track the runner's live message list (system prompt + history + current run)."""
    if session_key:
        _live_messages[session_key] = messages


def forget_live_messages(session_key: str | None) -> None:
    if session_key:
        _live_messages.pop(session_key, None)


def live_messages(session_key: str | None) -> list[dict[str, Any]] | None:
    return _live_messages.get(session_key) if session_key else None


def session_state(session: Session) -> dict[str, Any]:
    """Coworker-owned slice of ``session.metadata`` (persisted with the session)."""
    state = as_dict(session.metadata.get(COWORKER_META))
    if state is None:
        state = {}
        session.metadata[COWORKER_META] = state
    return state


def get_session(session_key: str | None) -> Session | None:
    svc = _services
    if svc is None or not session_key:
        return None
    return svc.sessions.get_or_create(session_key)


def runtime_for_preset(preset: str) -> LLMRuntime:
    """Resolve a configured model preset into a runnable runtime."""
    from nanobot.providers.factory import load_provider_snapshot
    from nanobot.utils.llm_runtime import runtime_from_provider_snapshot

    svc = _services
    if svc is not None and svc.provider_snapshot_loader is not None:
        snapshot = svc.provider_snapshot_loader(preset_name=preset)
    else:
        snapshot = load_provider_snapshot(preset_name=preset)
    return runtime_from_provider_snapshot(snapshot)


def turn_kind(metadata: dict[str, Any] | None) -> str | None:
    """Coworker kind of an injected turn, or None for ordinary turns."""
    if metadata and metadata.get("injected_event") == INJECTED_EVENT:
        kind = metadata.get(KIND_META)
        return kind if isinstance(kind, str) else None
    return None


def is_automated_turn(metadata: dict[str, Any] | None, session_key: str | None) -> bool:
    """Cron / trigger / dream turns must never be forced into advisor or room work."""
    if session_key and session_key.startswith(("dream:", "cron:", "heartbeat:")):
        return True
    if not metadata:
        return False
    return bool(metadata.get("_cron_trigger") or metadata.get("local_trigger") or metadata.get("heartbeat"))


async def inject_turn(
    *,
    session_key: str,
    channel: str,
    chat_id: str,
    content: str,
    kind: str,
    extra: dict[str, Any] | None = None,
) -> None:
    """Queue a harness-driven turn into ``session_key`` (the subagent-announce pattern)."""
    svc = _services
    if svc is None:
        logger.warning("coworker: cannot inject {} turn, services not bound", kind)
        return
    metadata: dict[str, Any] = {"injected_event": INJECTED_EVENT, KIND_META: kind, **(extra or {})}
    await svc.bus.publish_inbound(
        InboundMessage(
            channel="system",
            sender_id=f"coworker:{kind}",
            chat_id=f"{channel}:{chat_id}",
            content=content,
            session_key_override=session_key,
            metadata=metadata,
        )
    )


async def post_to_chat(*, channel: str, chat_id: str, content: str) -> None:
    """Deliver a message straight to the user's chat (no agent turn)."""
    svc = _services
    if svc is None:
        return
    await svc.bus.publish_outbound(
        OutboundMessage(channel=channel, chat_id=chat_id, content=content, metadata={"render_as": "text"})
    )


def spawn_background(coro: Coroutine[Any, Any, Any], *, name: str) -> asyncio.Task[Any]:
    task = asyncio.create_task(coro, name=name)
    _background.add(task)

    def _done(t: asyncio.Task[Any]) -> None:
        _background.discard(t)
        if not t.cancelled() and (exc := t.exception()) is not None:
            logger.opt(exception=exc).error("coworker background task {} failed", name)

    task.add_done_callback(_done)
    return task

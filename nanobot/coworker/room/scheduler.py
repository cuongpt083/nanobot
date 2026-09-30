"""Multi-agent room turn scheduler (session = room).

The session's own agent is the COORDINATOR. ``room_delegate`` records
(agent, task) during a turn; when that turn ends, a background room run executes
each teammate as an inline subagent with its own model preset and persona, posts
the reply to the chat with attribution, and finally re-summons the coordinator
with an ``[auto-room]`` review turn. Chained delegations are budgeted per user
message so agents can never loop forever. Port of AICoworker's room-turns.
"""

from __future__ import annotations

import asyncio
import re
import time
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from loguru import logger

from nanobot.coworker import directives
from nanobot.coworker.config import RoomAgentConfig, load_coworker_config
from nanobot.coworker.room.store import RoomTranscript, room_id_for
from nanobot.coworker.runtime import (
    get_session,
    inject_turn,
    post_to_chat,
    runtime_for_preset,
    services,
    session_state,
    spawn_background,
)
from nanobot.coworker.transcript import as_dict, is_genuine_user, message_text

if TYPE_CHECKING:
    from nanobot.session.manager import Session
    from nanobot.utils.llm_runtime import LLMRuntime

ROOM_MARKER = "[auto-room]"
KIND_ROOM_REVIEW = "room_review"
REPLY_SKIP = "REPLY_SKIP"
PROJECTION_MAX_CHARS = 24_000
PROJECTION_MAX_ENTRY_CHARS = 4000
REVIEW_MAX_REPLY_CHARS = 6000
_WAIT_FOR = re.compile(r"(?:^|\n)\s*WAIT_FOR\s+@?([a-z0-9_-]{1,64})\b", re.IGNORECASE)
_MENTION = re.compile(r"(?:^|[\s(\[{\"'.,;:!?])@([a-z0-9][a-z0-9_-]{0,63})", re.IGNORECASE)


@dataclass(frozen=True)
class RoomActor:
    """Identity of a teammate while its guest turn runs (read by room tools)."""

    room_id: str
    session_key: str
    agent_id: str


current_room_actor: ContextVar[RoomActor | None] = ContextVar("coworker_room_actor", default=None)


@dataclass(frozen=True)
class Delegation:
    agent_id: str
    task: str
    by: str


@dataclass(frozen=True)
class ActiveGuest:
    agent_id: str
    task: str
    started_at: float


@dataclass(frozen=True)
class GuestOutcome:
    agent_id: str
    state: str  # done | error | timeout
    finished_at: float


RECENT_OUTCOMES = 5


@dataclass
class _Room:
    session_key: str
    channel: str = ""
    chat_id: str = ""
    pending: list[Delegation] = field(default_factory=list)
    chained: int = 0
    owner_runtime: LLMRuntime | None = None
    task: asyncio.Task[Any] | None = None
    # Observability for the WebUI participants view (never read by the scheduler itself).
    active: dict[str, ActiveGuest] = field(default_factory=dict)
    queued: list[Delegation] = field(default_factory=list)
    waiting: dict[str, str] = field(default_factory=dict)  # agent id -> agent it waits for
    recent: list[GuestOutcome] = field(default_factory=list)

    def outcome(self, agent_id: str, state: str) -> None:
        self.recent.append(GuestOutcome(agent_id=agent_id, state=state, finished_at=time.time()))
        del self.recent[:-RECENT_OUTCOMES]


@dataclass(frozen=True)
class RoomSnapshot:
    active: list[ActiveGuest]
    queued: list[Delegation]
    waiting: dict[str, str]
    recent: list[GuestOutcome]


def room_snapshot(session_key: str) -> RoomSnapshot:
    """Point-in-time view of who is working, queued, waiting or recently finished."""
    room = _rooms.get(room_id_for(session_key))
    if room is None:
        return RoomSnapshot([], [], {}, [])
    queued = [*room.queued, *(d for d in room.pending if d not in room.queued)]
    return RoomSnapshot(
        active=list(room.active.values()),
        queued=queued,
        waiting=dict(room.waiting),
        recent=list(room.recent),
    )


_rooms: dict[str, _Room] = {}


def _room(session_key: str) -> _Room:
    rid = room_id_for(session_key)
    room = _rooms.get(rid)
    if room is None:
        room = _rooms[rid] = _Room(session_key=session_key)
    return room


# ---------- arming ----------

def is_armed(session: Session | None) -> bool:
    if session is None:
        return False
    slot = as_dict(session_state(session).get("room"))
    return slot is not None and slot.get("armed") is True


def set_armed(session: Session, armed: bool) -> None:
    session_state(session)["room"] = {"armed": armed}


def mentioned_agents(text: str) -> list[str]:
    cfg = load_coworker_config()
    known = {a.id for a in cfg.room.agents}
    seen: list[str] = []
    for match in _MENTION.finditer(text or ""):
        agent_id = match.group(1).lower()
        if agent_id in known and agent_id not in seen:
            seen.append(agent_id)
    return seen


# ---------- delegation buffer ----------

def record_delegation(
    session_key: str,
    agent_id: str,
    task: str,
    *,
    by: str,
    runtime: LLMRuntime | None,
) -> None:
    room = _room(session_key)
    agent_id = agent_id.strip().lstrip("@").lower()
    if agent_id == by:
        return  # self-delegation would loop
    # De-dupe per agent (last task wins) so a double call never double-runs.
    room.pending = [d for d in room.pending if d.agent_id != agent_id]
    room.pending.append(Delegation(agent_id=agent_id, task=task.strip(), by=by))
    if runtime is not None and by == "owner":
        room.owner_runtime = runtime


def pending_delegations(session_key: str) -> list[Delegation]:
    return list(_room(session_key).pending)


def reset_chain_budget(session_key: str) -> None:
    _room(session_key).chained = 0


def maybe_start_room_run(session_key: str, *, channel: str, chat_id: str) -> bool:
    """Called when a coordinator turn ends: run teammates if any were delegated."""
    room = _room(session_key)
    if channel and channel != "system":
        room.channel, room.chat_id = channel, chat_id
    if not room.pending or (room.task is not None and not room.task.done()):
        return False
    if not room.channel:
        logger.warning("room {}: no delivery route, dropping {} delegation(s)", session_key, len(room.pending))
        room.pending.clear()
        return False
    room.task = spawn_background(_run_room(room), name=f"coworker-room:{room_id_for(session_key)}")
    return True


# ---------- room run ----------

def _label(agent: RoomAgentConfig) -> str:
    return f"{agent.emoji + ' ' if agent.emoji else ''}{agent.name or agent.id}"


def _projection(room: _Room, session: Session | None) -> str:
    lines: list[str] = []
    if session is not None:
        request = next((message_text(m) for m in reversed(session.messages) if is_genuine_user(m)), "")
        if request:
            lines.append(f"User request: {request[:PROJECTION_MAX_ENTRY_CHARS]}")
    entries: list[str] = []
    for entry in RoomTranscript(_workspace(), room_id_for(room.session_key)).entries():
        text = str(entry.get("text", ""))
        if len(text) > PROJECTION_MAX_ENTRY_CHARS:
            text = text[:PROJECTION_MAX_ENTRY_CHARS] + "\n[... truncated]"
        entries.append(f"{entry.get('speaker', '?')}: {text}")
    total = sum(len(e) for e in entries)
    while len(entries) > 1 and total > PROJECTION_MAX_CHARS:
        total -= len(entries.pop(0))
    if entries:
        lines += ["", "Room so far:", *entries]
    return "\n".join(lines)


def _workspace():
    svc = services()
    if svc is None:
        raise RuntimeError("coworker services are not bound")
    return svc.workspace


async def _run_guest(room: _Room, agent: RoomAgentConfig, delegation: Delegation) -> str | None:
    svc = services()
    cfg = load_coworker_config()
    if agent.backend:
        from nanobot.coworker.coding.runner import CodingRunner

        runner = CodingRunner(cfg, _workspace())
        task, backend_obj, repo_cfg = runner.admit(
            brief=delegation.task,
            session_key=room.session_key,
            channel=room.channel,
            chat_id=room.chat_id,
            backend_name=agent.backend,
        )
        return await asyncio.wait_for(
            runner.execute_task(task, backend_obj, repo_cfg, wait=True),
            timeout=cfg.room.guest_timeout_seconds,
        )

    if svc is None or svc.subagents is None:
        raise RuntimeError("subagent manager unavailable")
    runtime = runtime_for_preset(agent.preset) if agent.preset else room.owner_runtime
    if runtime is None:
        runtime = runtime_for_preset("default")
    session = get_session(room.session_key)
    prompt = "\n\n".join([
        directives.room_guest(agent, "the room coordinator", cfg.room.agents),
        f"## Your assignment (from {delegation.by})\n{delegation.task}",
        "---",
        _projection(room, session),
    ])
    token = current_room_actor.set(
        RoomActor(room_id=room_id_for(room.session_key), session_key=room.session_key, agent_id=agent.id)
    )
    try:
        result = await asyncio.wait_for(
            svc.subagents.run_inline(
                task=prompt,
                label=f"room:{agent.id}",
                origin_channel=room.channel,
                origin_chat_id=room.chat_id,
                session_key=room.session_key,
                runtime=runtime,
            ),
            timeout=cfg.room.guest_timeout_seconds,
        )
    finally:
        current_room_actor.reset(token)
    text = str(result or "").strip()
    return text or None


async def _run_room(room: _Room) -> None:
    cfg = load_coworker_config()
    transcript = RoomTranscript(_workspace(), room_id_for(room.session_key))
    queue = list(room.pending)
    room.pending.clear()
    results: list[tuple[RoomAgentConfig, str]] = []
    waited: set[str] = set()
    budget_note = False

    async def note(text: str) -> None:
        await post_to_chat(channel=room.channel, chat_id=room.chat_id, content=text)

    try:
        while True:
            if not queue:
                # Delegations recorded while this run was busy (coordinator or teammates).
                queue, room.pending = room.pending, []
                if not queue:
                    break
            delegation = queue.pop(0)
            room.queued = list(queue)
            if room.chained >= cfg.room.max_chained_turns:
                if not budget_note:
                    budget_note = True
                    await note(
                        f"⏸️ Room paused: chained-turn budget ({cfg.room.max_chained_turns}) exhausted — "
                        "send a new message to continue."
                    )
                continue
            agent = cfg.agent(delegation.agent_id)
            if agent is None:
                await note(f"⚠️ Unknown room agent `{delegation.agent_id}` — skipped.")
                continue
            room.chained += 1
            transcript.append(f"{delegation.by} → @{agent.id}", delegation.task)
            await note(f"⏳ {_label(agent)} is working on: {delegation.task[:200]}")
            room.waiting.pop(agent.id, None)
            room.active[agent.id] = ActiveGuest(agent.id, delegation.task, time.time())
            try:
                reply = await _run_guest(room, agent, delegation)
            except TimeoutError:
                room.outcome(agent.id, "timeout")
                await note(f"⚠️ {_label(agent)} did not finish within {cfg.room.guest_timeout_seconds}s — stopped.")
                continue
            except Exception as exc:
                room.outcome(agent.id, "error")
                logger.opt(exception=exc).warning("room {}: guest @{} failed", room.session_key, agent.id)
                await note(f"⚠️ {_label(agent)} failed: {type(exc).__name__}")
                continue
            finally:
                room.active.pop(agent.id, None)
            # Delegations the teammate made during its turn join the queue in order.
            queue.extend(room.pending)
            room.pending = []
            room.queued = list(queue)
            if not reply or reply.strip() == REPLY_SKIP:
                room.outcome(agent.id, "done")
                continue
            wait = _WAIT_FOR.search(reply)
            if wait and agent.id not in waited:
                target = wait.group(1).lower()
                if any(d.agent_id == target for d in queue):
                    waited.add(agent.id)
                    queue.append(delegation)
                    room.queued = list(queue)
                    room.waiting[agent.id] = target
                    await note(f"⏳ {_label(agent)} waits for @{target} first (data dependency).")
                    continue
            room.outcome(agent.id, "done")
            transcript.append(f"@{agent.id}", reply)
            await note(f"{_label(agent)}:\n{reply}")
            results.append((agent, reply))
    finally:
        room.queued = []
        room.active.clear()
        room.waiting.clear()

    if results:
        await _summon_coordinator(room, results)


async def _summon_coordinator(room: _Room, results: list[tuple[RoomAgentConfig, str]]) -> None:
    parts = [f"{ROOM_MARKER} Your teammates finished their delegated parts:"]
    for agent, reply in results:
        body = reply if len(reply) <= REVIEW_MAX_REPLY_CHARS else reply[:REVIEW_MAX_REPLY_CHARS] + "\n[... truncated]"
        parts.append(f"\n### {_label(agent)} (`{agent.id}`)\n{body}")
    parts.append(
        "\nReview each part now (verify with your tools, do not rubber-stamp), then post ONE final "
        "consolidated report for the user. If a part is wrong or missing, call room_delegate with the "
        "specific fix instead. Credit teammates by name."
    )
    await inject_turn(
        session_key=room.session_key,
        channel=room.channel,
        chat_id=room.chat_id,
        content="\n".join(parts),
        kind=KIND_ROOM_REVIEW,
    )


def reset_rooms() -> None:
    """Test hook."""
    _rooms.clear()

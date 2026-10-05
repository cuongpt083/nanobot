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
import json
import re
import secrets
import time
from contextvars import ContextVar
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any

from loguru import logger

from nanobot.coworker import directives
from nanobot.coworker.config import RoomAgentConfig, load_coworker_config
from nanobot.coworker.room.store import RoomStateStore, RoomTranscript, room_id_for, rooms_dir
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
    from nanobot.coworker.agents.runtime import GuestResult
    from nanobot.session.manager import Session
    from nanobot.utils.llm_runtime import LLMRuntime

ROOM_MARKER = "[auto-room]"
KIND_ROOM_REVIEW = "room_review"
REPLY_SKIP = "REPLY_SKIP"
PROJECTION_MAX_CHARS = 24_000
PROJECTION_MAX_ENTRY_CHARS = 4000
REVIEW_MAX_REPLY_CHARS = 6000
USER_TURN_MAX_CHARS = 1500
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
    id: str = ""
    context: str = ""
    context_keys: tuple[str, ...] = ()
    after: tuple[str, ...] = ()
    deliverable: str = ""


@dataclass
class ActiveGuest:
    agent_id: str
    task: str
    started_at: float
    iteration: int = 0
    last_tool: str | None = None


@dataclass(frozen=True)
class GuestOutcome:
    agent_id: str
    state: str  # done | error | timeout
    finished_at: float
    duration_s: float = 0.0
    tokens_in: int | None = None
    tokens_out: int | None = None


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
    last_guest: dict[str, GuestResult] = field(default_factory=dict)

    def outcome(
        self,
        agent_id: str,
        state: str,
        *,
        duration_s: float = 0.0,
        tokens_in: int | None = None,
        tokens_out: int | None = None,
    ) -> None:
        self.recent.append(
            GuestOutcome(
                agent_id=agent_id,
                state=state,
                finished_at=time.time(),
                duration_s=duration_s,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
            )
        )
        del self.recent[:-RECENT_OUTCOMES]
        logger.info(
            "room guest finished: room={} agent={} state={} duration_s={:.2f} tokens_in={} tokens_out={}",
            self.session_key,
            agent_id,
            state,
            duration_s,
            tokens_in,
            tokens_out,
        )


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


def mention_ids(text: str) -> list[str]:
    """Every distinct ``@name`` in the text (lowercased, in order), configured or not."""
    seen: list[str] = []
    for match in _MENTION.finditer(text or ""):
        name = match.group(1).lower()
        if name not in seen:
            seen.append(name)
    return seen


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

def _short_id() -> str:
    return secrets.token_hex(3)


def known_delegate_targets(session_key: str) -> set[str]:
    """Agent ids already queued, running, or finished in this room (for `after`)."""
    room = _room(session_key)
    ids = {d.agent_id for d in room.pending}
    ids.update(d.agent_id for d in room.queued)
    ids.update(room.active)
    ids.update(room.last_guest)
    return ids


def record_delegation(
    session_key: str,
    agent_id: str,
    task: str,
    *,
    by: str,
    runtime: LLMRuntime | None,
    context: str = "",
    context_keys: list[str] | tuple[str, ...] | None = None,
    after: list[str] | tuple[str, ...] | None = None,
    deliverable: str = "",
    delegation_id: str | None = None,
) -> Delegation:
    room = _room(session_key)
    agent_id = agent_id.strip().lstrip("@").lower()
    if agent_id == by:
        return Delegation(agent_id=agent_id, task=task.strip(), by=by)
    keys = tuple(k.strip() for k in (context_keys or ()) if str(k).strip())
    deps = tuple(a.strip().lstrip("@").lower() for a in (after or ()) if str(a).strip())
    # De-dupe per agent (last task wins) so a double call never double-runs.
    room.pending = [d for d in room.pending if d.agent_id != agent_id]
    delegation = Delegation(
        agent_id=agent_id,
        task=task.strip(),
        by=by,
        id=delegation_id or _short_id(),
        context=(context or "").strip(),
        context_keys=keys,
        after=deps,
        deliverable=(deliverable or "").strip(),
    )
    room.pending.append(delegation)
    if runtime is not None and by == "owner":
        room.owner_runtime = runtime
    return delegation


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


def _clip(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "\n[... truncated]"


def _recent_user_turns(session: Session | None, *, turns: int) -> list[str]:
    if session is None or turns <= 0:
        return []
    texts = [message_text(m) for m in session.messages if is_genuine_user(m)]
    return [_clip(t, USER_TURN_MAX_CHARS) for t in texts[-turns:] if t.strip()]


def _shared_state_block(room: _Room, keys: tuple[str, ...]) -> str:
    if not keys:
        return ""
    store = RoomStateStore(_workspace(), room_id_for(room.session_key))
    lines: list[str] = []
    for key in keys:
        entry = store.get(key)
        if entry is None:
            lines.append(f"- `{key}`: (missing)")
            continue
        try:
            rendered = json.dumps(entry.value, ensure_ascii=False)
        except (TypeError, ValueError):
            rendered = str(entry.value)
        lines.append(f"- `{key}` (by {entry.by}): {_clip(rendered, 2000)}")
    return "\n".join(lines)


def _upstream_block(room: _Room, after: tuple[str, ...]) -> str:
    if not after:
        return ""
    lines: list[str] = []
    for dep in after:
        guest = room.last_guest.get(dep)
        if guest is None:
            lines.append(f"- @{dep}: (not finished yet)")
            continue
        contract = guest.contract or {}
        summary = str(contract.get("summary") or guest.text or "").strip()
        artifacts = contract.get("artifacts") if isinstance(contract.get("artifacts"), list) else []
        lines.append(f"- @{dep}: {_clip(summary, 1200)}")
        if artifacts:
            lines.append(f"  artifacts: {', '.join(str(a) for a in artifacts)}")
    return "\n".join(lines)


def _task_message(room: _Room, session: Session | None, delegation: Delegation) -> str:
    """Structured assignment for a guest; tail is dropped first if over budget."""
    cfg = load_coworker_config()
    assignment_bits = [f"## Assignment\nFrom {delegation.by}\n{delegation.task}"]
    if delegation.deliverable:
        assignment_bits.append(f"Deliverable: {delegation.deliverable}")
    if delegation.agent_id:
        try:
            artifacts = rooms_dir(_workspace()) / room_id_for(room.session_key) / "artifacts" / delegation.agent_id
            assignment_bits.append(f"Long files: `{artifacts.as_posix()}`")
        except RuntimeError:
            pass
    sections: list[tuple[int, str]] = [(0, "\n".join(assignment_bits))]
    if delegation.context:
        sections.append((1, f"## Context from coordinator\n{delegation.context}"))
    shared = _shared_state_block(room, delegation.context_keys)
    if shared:
        sections.append((2, f"## Shared state\n{shared}"))
    upstream = _upstream_block(room, delegation.after)
    if upstream:
        sections.append((3, f"## Upstream results\n{upstream}"))
    user_turns = _recent_user_turns(session, turns=cfg.room.context_turns)
    if user_turns:
        numbered = "\n\n".join(f"{i + 1}. {t}" for i, t in enumerate(user_turns))
        sections.append((4, f"## Recent user turns\n{numbered}"))
    entries: list[str] = []
    for entry in RoomTranscript(_workspace(), room_id_for(room.session_key)).entries():
        text = _clip(str(entry.get("text", "")), PROJECTION_MAX_ENTRY_CHARS)
        entries.append(f"{entry.get('speaker', '?')}: {text}")
    if entries:
        sections.append((5, "## Room so far\n" + "\n".join(entries)))

    def packed(items: list[tuple[int, str]]) -> str:
        return "\n\n".join(body for _, body in items)

    while len(sections) > 1 and len(packed(sections)) > PROJECTION_MAX_CHARS:
        sections.pop()
    text = packed(sections)
    if len(text) > PROJECTION_MAX_CHARS:
        text = text[:PROJECTION_MAX_CHARS] + "\n[... truncated]"
    return text


def _projection(room: _Room, session: Session | None) -> str:
    """Legacy helper kept for tests that inspect the old transcript-only shape."""
    return _task_message(
        room,
        session,
        Delegation(agent_id="", task="", by="owner"),
    )


def _workspace():
    svc = services()
    if svc is None:
        raise RuntimeError("coworker services are not bound")
    return svc.workspace


async def _run_guest(room: _Room, agent: RoomAgentConfig, delegation: Delegation) -> GuestResult | None:
    from nanobot.coworker.agents.prompt import resolve_home
    from nanobot.coworker.agents.runtime import AgentRuntime, GuestResult

    svc = services()
    cfg = load_coworker_config()
    if agent.backend:
        from nanobot.coworker.coding.runner import CodingRunner

        runner = CodingRunner(cfg, _workspace())
        task, backend_obj, repo_cfg = await runner.admit_async(
            brief=delegation.task,
            session_key=room.session_key,
            channel=room.channel,
            chat_id=room.chat_id,
            backend_name=agent.backend,
        )
        text = await asyncio.wait_for(
            runner.execute_task(task, backend_obj, repo_cfg, wait=True),
            timeout=cfg.room.guest_timeout_seconds,
        )
        cleaned = str(text or "").strip()
        return GuestResult(text=cleaned) if cleaned else None

    if svc is None:
        raise RuntimeError("coworker services are not bound")
    runtime = runtime_for_preset(agent.preset) if agent.preset else room.owner_runtime
    if runtime is None:
        runtime = runtime_for_preset("default")
    session = get_session(room.session_key)
    assignment = _task_message(room, session, delegation)
    use_legacy = cfg.room.legacy_guest_runner or resolve_home(agent, svc.workspace) is None
    token = current_room_actor.set(
        RoomActor(room_id=room_id_for(room.session_key), session_key=room.session_key, agent_id=agent.id)
    )
    try:
        if use_legacy:
            if svc.subagents is None:
                raise RuntimeError("subagent manager unavailable")
            prompt = "\n\n".join([
                directives.room_guest(agent, "the room coordinator", cfg.room.agents),
                assignment,
            ])
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
            text = str(result or "").strip()
            return GuestResult(text=text) if text else None

        from nanobot.security.workspace_access import workspace_scope_from_metadata

        restrict_default = bool(svc.tools_config and svc.tools_config.restrict_to_workspace)
        scope = workspace_scope_from_metadata(
            getattr(session, "metadata", None) if session is not None else None,
            default_workspace=svc.workspace,
            default_restrict_to_workspace=restrict_default,
        )
        guest = await asyncio.wait_for(
            AgentRuntime(svc, cfg).run(
                agent,
                assignment,
                room_id=room_id_for(room.session_key),
                session_key=room.session_key,
                channel=room.channel,
                chat_id=room.chat_id,
                project_root=scope.project_path,
                runtime=runtime,
                progress=room.active.get(agent.id),
                workspace_scope=scope,
            ),
            timeout=cfg.room.guest_timeout_seconds,
        )
        return guest
    finally:
        current_room_actor.reset(token)


async def _run_room(room: _Room) -> None:
    cfg = load_coworker_config()
    transcript = RoomTranscript(_workspace(), room_id_for(room.session_key))
    queue = list(room.pending)
    room.pending.clear()
    room.queued = list(queue)
    results: list[tuple[RoomAgentConfig, str]] = []
    waited: set[str] = set()
    finished: set[str] = set(room.last_guest)
    budget_note = False

    running: dict[str, asyncio.Task[GuestResult | None]] = {}
    running_info: dict[str, tuple[RoomAgentConfig, Delegation, float]] = {}

    async def note(text: str) -> None:
        await post_to_chat(channel=room.channel, chat_id=room.chat_id, content=text)

    async def _handle_finished(
        agent: RoomAgentConfig,
        delegation: Delegation,
        guest_t0: float,
        exc: BaseException | None,
        guest: GuestResult | None,
    ) -> None:
        nonlocal budget_note
        room.active.pop(agent.id, None)
        duration_s = time.monotonic() - guest_t0

        if isinstance(exc, TimeoutError):
            room.outcome(agent.id, "timeout", duration_s=duration_s)
            finished.add(agent.id)
            await note(f"⚠️ {_label(agent)} did not finish within {cfg.room.guest_timeout_seconds}s — stopped.")
            return

        if exc is not None:
            room.outcome(agent.id, "error", duration_s=duration_s)
            finished.add(agent.id)
            logger.opt(exception=exc).warning("room {}: guest @{} failed", room.session_key, agent.id)
            # ProjectError / RuntimeError from coding admission carry an actionable,
            # user-facing reason (pick a project dir, make it a git repo, install backend...).
            detail = (
                f"{type(exc).__name__}: {str(exc)[:400]}"
                if isinstance(exc, RuntimeError) and str(exc)
                else type(exc).__name__
            )
            await note(f"⚠️ {_label(agent)} failed: {detail}")
            return

        if guest is not None:
            room.last_guest[agent.id] = guest
        reply = (guest.text if guest is not None else "").strip()
        tokens_in = guest.usage.get("prompt_tokens") if guest is not None else None
        tokens_out = guest.usage.get("completion_tokens") if guest is not None else None

        # Delegations the teammate made during its turn join the queue in order.
        if room.pending:
            queue.extend(room.pending)
            room.pending.clear()
            room.queued = list(queue)

        if not reply or reply == REPLY_SKIP:
            finished.add(agent.id)
            room.outcome(
                agent.id, "done", duration_s=duration_s, tokens_in=tokens_in, tokens_out=tokens_out,
            )
            return

        wait = _WAIT_FOR.search(reply)
        if wait and agent.id not in waited:
            target = wait.group(1).lower()
            still_pending = (
                target not in finished
                and (
                    any(item.agent_id == target for item in queue)
                    or any(item.agent_id == target for item in room.pending)
                    or target in running
                )
            )
            if still_pending:
                waited.add(agent.id)
                queue.append(replace(
                    delegation,
                    after=tuple(dict.fromkeys([*delegation.after, target])),
                ))
                room.queued = list(queue)
                room.waiting[agent.id] = target
                await note(f"⏳ {_label(agent)} waits for @{target} first (data dependency).")
                return

        finished.add(agent.id)
        if guest is not None and guest.contract_failed:
            await note(
                f"⚠️ {_label(agent)} did not return a valid output contract "
                "(confidence treated as low)."
            )
        room.outcome(
            agent.id, "done", duration_s=duration_s, tokens_in=tokens_in, tokens_out=tokens_out,
        )
        transcript.append(f"@{agent.id}", reply)
        await note(f"{_label(agent)}:\n{reply}")
        results.append((agent, reply))

    try:
        while True:
            # Delegations recorded while this run was busy (coordinator or teammates).
            if room.pending:
                queue.extend(room.pending)
                room.pending.clear()
                room.queued = list(queue)

            max_parallel = max(1, cfg.room.max_parallel)
            while len(running) < max_parallel and room.chained < cfg.room.max_chained_turns:
                ready_idx = None
                for i, item in enumerate(queue):
                    if item.agent_id not in running and all(dep in finished for dep in item.after):
                        ready_idx = i
                        break
                if ready_idx is None:
                    break

                delegation = queue.pop(ready_idx)
                room.queued = list(queue)
                agent = cfg.agent(delegation.agent_id)
                if agent is None:
                    await note(f"⚠️ Unknown room agent `{delegation.agent_id}` — skipped.")
                    finished.add(delegation.agent_id)
                    continue

                room.chained += 1
                transcript.append(f"{delegation.by} → @{agent.id}", delegation.task)
                await note(f"⏳ {_label(agent)} is working on: {delegation.task[:200]}")
                room.waiting.pop(agent.id, None)
                room.active[agent.id] = ActiveGuest(agent.id, delegation.task, time.time())
                guest_t0 = time.monotonic()

                coro = _run_guest(room, agent, delegation)
                task = asyncio.create_task(
                    coro,
                    name=f"coworker-guest:{room_id_for(room.session_key)}:{agent.id}",
                )
                running[agent.id] = task
                running_info[agent.id] = (agent, delegation, guest_t0)

            if queue and room.chained >= cfg.room.max_chained_turns and not running:
                if not budget_note:
                    budget_note = True
                    await note(
                        f"⏸️ Room paused: chained-turn budget ({cfg.room.max_chained_turns}) exhausted — "
                        "send a new message to continue."
                    )
                queue.clear()
                room.queued = []
                break

            if not running and not queue and not room.pending:
                break

            if not running and queue:
                blocked = "; ".join(
                    f"@{item.agent_id} waits for {', '.join('@' + dep for dep in item.after)}"
                    for item in queue
                )
                await note(f"⚠️ Dependencies could not be resolved: {blocked}")
                queue.clear()
                room.queued = []
                break

            done, _ = await asyncio.wait(
                running.values(),
                return_when=asyncio.FIRST_COMPLETED,
            )
            for finished_task in done:
                matched_id = next(aid for aid, t in running.items() if t == finished_task)
                running.pop(matched_id)
                agent, delegation, guest_t0 = running_info.pop(matched_id)
                exc = finished_task.exception() if not finished_task.cancelled() else None
                guest = finished_task.result() if (exc is None and not finished_task.cancelled()) else None
                await _handle_finished(agent, delegation, guest_t0, exc, guest)

    finally:
        for t in running.values():
            t.cancel()
        if running:
            await asyncio.gather(*running.values(), return_exceptions=True)
        room.queued = []
        room.active.clear()
        room.waiting.clear()

    if results:
        await _summon_coordinator(room, results, last_guest=dict(room.last_guest))
    room.last_guest.clear()


async def _summon_coordinator(
    room: _Room,
    results: list[tuple[RoomAgentConfig, str]],
    last_guest: dict[str, GuestResult] | None = None,
) -> None:
    guests = last_guest or {}
    ranked: list[tuple[int, RoomAgentConfig, str]] = []
    for agent, reply in results:
        ranked.append((_review_priority(guests.get(agent.id)), agent, reply))
    ranked.sort(key=lambda item: item[0])
    parts = [f"{ROOM_MARKER} Your teammates finished their delegated parts:"]
    for _, agent, reply in ranked:
        guest = guests.get(agent.id)
        contract = guest.contract if guest is not None else None
        if contract:
            summary = str(contract.get("summary") or "").strip()
            confidence = contract.get("confidence") or "low"
            artifacts = contract.get("artifacts") if isinstance(contract.get("artifacts"), list) else []
            questions = contract.get("open_questions") if isinstance(contract.get("open_questions"), list) else []
            body_lines = [
                f"confidence: {confidence}",
                f"summary: {summary}" if summary else "summary: (empty)",
            ]
            if artifacts:
                body_lines.append("artifacts: " + ", ".join(str(a) for a in artifacts))
                body_lines.append("Open artifacts with read_file before you approve.")
            if questions:
                body_lines.append("open_questions: " + "; ".join(str(q) for q in questions))
            body = "\n".join(body_lines)
        else:
            clipped = reply if len(reply) <= REVIEW_MAX_REPLY_CHARS else reply[:REVIEW_MAX_REPLY_CHARS] + "\n[... truncated]"
            if guest is not None and guest.contract_failed:
                body = (
                    "confidence: low\n"
                    "summary: (output contract missing or invalid)\n"
                    f"{clipped}"
                )
            else:
                body = clipped
        parts.append(f"\n### {_label(agent)} (`{agent.id}`)\n{body}")
    parts.append(
        "\nReview each part now (verify with your tools, do not rubber-stamp), then post ONE final "
        "consolidated report for the user. If a part is wrong or missing, call room_delegate with the "
        "specific fix instead. Credit teammates by name. Open listed artifacts with read_file before approving."
    )
    await inject_turn(
        session_key=room.session_key,
        channel=room.channel,
        chat_id=room.chat_id,
        content="\n".join(parts),
        kind=KIND_ROOM_REVIEW,
    )


def _review_priority(guest: GuestResult | None) -> int:
    """0 = needs attention first (low confidence, open questions, or failed contract)."""
    if guest is None:
        return 1
    if guest.contract_failed:
        return 0
    contract = guest.contract
    if not contract:
        return 1
    questions = contract.get("open_questions")
    if contract.get("confidence") == "low" or (isinstance(questions, list) and questions):
        return 0
    return 1


def reset_rooms() -> None:
    """Test hook."""
    _rooms.clear()

"""The browser session registry: which sessions nanobot owns, and stopping them (BrowserSkill Mức 2, Registry).

A session belongs to one ``(nanobot session key, agent id)`` pair. The registry only sees and stops sessions it
started, so a session made by a terminal or another agent on the same daemon is never touched. Starts are
recoverable: the request token is journaled and prepared before the browser is opened, and a start that
cannot be claimed is stopped again rather than left open.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from nanobot.coworker.browser.journal import BrowserJournal
from nanobot.coworker.browser.runner import BskError, BskRunner

TOKEN_TTL_MS = 5 * 60 * 1000  # the proposal's admission deadline; bsk accepts at most ten minutes
DEFAULT_MAX_PER_KEY = 2
DEFAULT_MAX_TOTAL = 5
DEFAULT_IDLE_TTL_S = 30 * 60


@dataclass
class OwnedSession:
    session_id: str
    key: str
    agent_id: str
    request_id: str
    keep_open: bool
    started_at: float
    last_used: float


class BrowserSessionRegistry:
    def __init__(
        self,
        runner: BskRunner,
        journal: BrowserJournal,
        *,
        max_per_key: int = DEFAULT_MAX_PER_KEY,
        max_total: int = DEFAULT_MAX_TOTAL,
        idle_ttl_s: float = DEFAULT_IDLE_TTL_S,
        clock: Callable[[], float] = time.monotonic,
        now_ms: Callable[[], int] = lambda: int(time.time() * 1000),
    ) -> None:
        self._runner = runner
        self._journal = journal
        self._max_per_key = max_per_key
        self._max_total = max_total
        self._idle_ttl_s = idle_ttl_s
        self._clock = clock
        self._now_ms = now_ms
        self._owned: dict[str, OwnedSession] = {}
        self._current: dict[tuple[str, str], str] = {}
        self._lock = asyncio.Lock()

    @property
    def runner(self) -> BskRunner:
        """The bsk runner, for commands that do not change which sessions are owned (inspect, interact)."""
        return self._runner

    # ---------- queries ----------

    def owned(self, key: str, agent_id: str) -> list[OwnedSession]:
        return [s for s in self._owned.values() if s.key == key and s.agent_id == agent_id]

    def current(self, key: str, agent_id: str) -> str | None:
        session_id = self._current.get((key, agent_id))
        if session_id in self._owned and self._owned[session_id].key == key:
            return session_id
        return None

    def assert_owned(self, session_id: str, key: str, agent_id: str) -> OwnedSession:
        owned = self._owned.get(session_id)
        if owned is None or owned.key != key or owned.agent_id != agent_id:
            raise BskError("not_owned", "that session was not started by this conversation")
        return owned

    def touch(self, session_id: str) -> None:
        owned = self._owned.get(session_id)
        if owned is not None:
            owned.last_used = self._clock()

    # ---------- lifecycle ----------

    def new_token(self) -> str:
        return f"{self._now_ms() + TOKEN_TTL_MS}:{uuid.uuid4()}"

    async def start(
        self,
        key: str,
        agent_id: str,
        *,
        keep_open: bool = False,
        name: str | None = None,
    ) -> OwnedSession:
        async with self._lock:
            if len(self.owned(key, agent_id)) >= self._max_per_key:
                raise BskError("limit", f"this conversation already has {self._max_per_key} browser sessions open",
                               hint="stop one with browser_session stop before starting another")
            if len(self._owned) >= self._max_total:
                raise BskError("limit", f"nanobot already has {self._max_total} browser sessions open",
                               hint="stop a session first")
            token = self.new_token()
            self._journal.append("start_intent", key=key, agent_id=agent_id, request_id=token)
            try:
                await self._runner.run(["session", "request", token, "--prepare"])
                args = ["session", "start", "--request-id", token]
                if name:
                    args += ["--name", name[:80]]
                reply = await self._runner.run(args, timeout=60.0)
            except BskError as exc:
                self._journal.append("start_failed", key=key, agent_id=agent_id, request_id=token, code=exc.code)
                raise
            session_id = reply.get("session_id")
            if not isinstance(session_id, str) or not session_id:
                raise BskError("bad_output", "bsk started a session without returning its id")
            self._journal.append("start_ok", key=key, agent_id=agent_id, request_id=token, session_id=session_id)
            try:
                await self._runner.run(["session", "request", token, "--claim"])
            except BskError:
                # The browser opened but was never claimed: close it now, do not leave it for the next turn.
                await self._stop_quietly(session_id, key, agent_id)
                raise
            now = self._clock()
            owned = OwnedSession(
                session_id=session_id, key=key, agent_id=agent_id, request_id=token,
                keep_open=keep_open, started_at=now, last_used=now,
            )
            self._owned[session_id] = owned
            self._current[(key, agent_id)] = session_id
            return owned

    async def stop(self, key: str, agent_id: str, session_id: str | None = None) -> dict[str, Any]:
        target = session_id or self.current(key, agent_id)
        if target is None:
            raise BskError("no_session", "there is no browser session to stop")
        self.assert_owned(target, key, agent_id)
        self._journal.append("stop_intent", key=key, agent_id=agent_id, session_id=target)
        reply = await self._runner.run(["session", "stop", target])
        self._forget(target, key, agent_id)
        return reply

    async def stop_all(self, key: str, agent_id: str, *, include_keep_open: bool = True) -> list[str]:
        stopped: list[str] = []
        for owned in list(self.owned(key, agent_id)):
            if owned.keep_open and not include_keep_open:
                continue
            try:
                await self.stop(key, agent_id, owned.session_id)
                stopped.append(owned.session_id)
            except BskError:
                # Keep the record: the next turn or the shutdown retries it.
                continue
        return stopped

    async def close_turn(self, key: str, agent_id: str) -> list[str]:
        """End of a turn: stop what was not asked to stay open, and sweep idle sessions that were."""
        stopped = await self.stop_all(key, agent_id, include_keep_open=False)
        stopped += await self.sweep_idle(key, agent_id)
        return stopped

    async def sweep_idle(self, key: str, agent_id: str) -> list[str]:
        now = self._clock()
        stopped: list[str] = []
        for owned in list(self.owned(key, agent_id)):
            if owned.keep_open and now - owned.last_used > self._idle_ttl_s:
                try:
                    await self.stop(key, agent_id, owned.session_id)
                    stopped.append(owned.session_id)
                except BskError:
                    continue
        return stopped

    async def shutdown(self) -> list[str]:
        """Stop every session this process owns (nanobot is shutting down)."""
        stopped: list[str] = []
        for owned in list(self._owned.values()):
            try:
                await self.stop(owned.key, owned.agent_id, owned.session_id)
                stopped.append(owned.session_id)
            except BskError:
                continue
        return stopped

    async def recover(self) -> list[str]:
        """After a restart: stop the sessions the journal shows as started and never stopped."""
        stopped: list[str] = []
        for record in self._journal.open_sessions():
            try:
                await self._runner.run(["session", "stop", record.session_id])
            except BskError:
                continue
            self._journal.append("stopped", key=record.key, agent_id=record.agent_id, session_id=record.session_id)
            stopped.append(record.session_id)
        return stopped

    # ---------- internals ----------

    def _forget(self, session_id: str, key: str, agent_id: str) -> None:
        self._journal.append("stopped", key=key, agent_id=agent_id, session_id=session_id)
        self._owned.pop(session_id, None)
        if self._current.get((key, agent_id)) == session_id:
            remaining = self.owned(key, agent_id)
            if remaining:
                self._current[(key, agent_id)] = remaining[-1].session_id
            else:
                self._current.pop((key, agent_id), None)

    async def _stop_quietly(self, session_id: str, key: str, agent_id: str) -> None:
        try:
            await self._runner.run(["session", "stop", session_id])
        except BskError:
            return
        self._journal.append("stopped", key=key, agent_id=agent_id, session_id=session_id)

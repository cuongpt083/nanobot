"""Pilot service managing capture lifecycle, worker threads, and queue drain."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from loguru import logger

from nanobot.agent.hook import AgentTurnHookContext
from nanobot.pilot.capture import DistillationCaptureHook
from nanobot.pilot.consent import ConsentGate
from nanobot.pilot.identity import IdentityHasher
from nanobot.pilot.metrics import pilot_metrics
from nanobot.pilot.queue import CaptureQueue
from nanobot.pilot.redaction import Redactor
from nanobot.pilot.store import SQLitePilotStore


class PilotService:
    """Service encapsulating the capture queue, SQLite store, and background writer."""

    def __init__(
        self,
        db_path: Path | str = "~/.nanobot/pilot_events.db",
        hmac_secret: str = "default_pilot_secret_change_me",
        operator_enabled: bool = True,
        queue_capacity: int = 1000,
    ) -> None:
        expanded_path = Path(db_path).expanduser() if isinstance(db_path, str) else db_path
        self.store = SQLitePilotStore(expanded_path)
        self.queue = CaptureQueue(capacity=queue_capacity)
        self.hasher = IdentityHasher(secret=hmac_secret)
        self.redactor = Redactor()
        self.consent_gate = ConsentGate(operator_enabled=operator_enabled)

        self._writer_task: asyncio.Task | None = None
        self._running = False

    async def start(self) -> None:
        """Start the background writer task."""
        if self._running:
            return
        self._running = True
        self._writer_task = asyncio.create_task(self._writer_loop())

    async def stop(self, flush_timeout_seconds: float = 5.0) -> None:
        """Stop writer task and flush pending queue events."""
        if not self._running:
            return
        self._running = False
        await self.queue.close()

        if self._writer_task:
            try:
                await asyncio.wait_for(self._writer_task, timeout=flush_timeout_seconds)
            except asyncio.TimeoutError:
                logger.warning("PilotService writer loop flush timed out")
            except Exception as ex:
                logger.warning(f"PilotService writer loop error on stop: {ex}")

        self.store.close()

    async def _writer_loop(self) -> None:
        """Background task that drains queue events into SQLite via asyncio.to_thread."""
        while self._running:
            batch = await self.queue.get_batch(max_items=100)
            if not batch:
                break

            try:
                await asyncio.to_thread(self.store.write_batch, batch)
                for item in batch:
                    pilot_metrics.inc_events_persisted(item.kind)
            except Exception as ex:
                pilot_metrics.inc_hook_error()
                logger.error(f"Failed to persist pilot event batch: {ex}")

    def hook_factory(self, context: AgentTurnHookContext) -> DistillationCaptureHook:
        """Factory for constructing per-turn DistillationCaptureHook."""
        return DistillationCaptureHook(
            turn_context=context,
            queue=self.queue,
            hasher=self.hasher,
            redactor=self.redactor,
            consent_gate=self.consent_gate,
            store=self.store,
        )

    async def health_snapshot(self) -> dict[str, Any]:
        """Return operational health snapshot of capture service."""
        q_snap = await self.queue.snapshot()
        return {
            "status": "ok" if self._running else "stopped",
            "queue_depth": q_snap.depth,
            "queue_capacity": q_snap.capacity,
            "accepted_total": q_snap.accepted_total,
            "metrics": pilot_metrics.snapshot(),
        }

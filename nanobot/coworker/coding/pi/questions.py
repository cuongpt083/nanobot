from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

from loguru import logger


@dataclass
class PendingQuestion:
    question_id: str
    task_id: str
    question: str
    blocking_reason: str
    options: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    escalated: bool = False
    answer: str | None = None
    cancelled: bool = False


class QuestionRouter:
    """Manages routing of extension questions (ask_coordinator) to coordinator agent/user."""

    def __init__(
        self,
        *,
        default_timeout_s: float = 600.0,
        user_timeout_s: float = 3600.0,
        on_question_created: Callable[[PendingQuestion], Any] | None = None,
    ) -> None:
        self.default_timeout_s = default_timeout_s
        self.user_timeout_s = user_timeout_s
        self.on_question_created = on_question_created
        self._pending: dict[str, PendingQuestion] = {}
        self._waiters: dict[str, asyncio.Future[dict[str, Any]]] = {}
        self._timers: dict[str, asyncio.TimerHandle] = {}

    def get_pending(self, question_id: str) -> PendingQuestion | None:
        return self._pending.get(question_id)

    def list_pending_for_task(self, task_id: str) -> list[PendingQuestion]:
        return [q for q in self._pending.values() if q.task_id == task_id and not q.cancelled and q.answer is None]

    async def handle_extension_ui_request(
        self,
        request_id: str,
        task_id: str,
        method: str,
        title: str,
        message: str,
        options: list[str] | None = None,
    ) -> dict[str, Any]:
        """Handles an incoming extension_ui_request for questions."""
        if not title.startswith("nanobot:ask:"):
            return {"cancelled": True}

        blocking_reason = title[len("nanobot:ask:"):]
        question = message or title

        pending = PendingQuestion(
            question_id=request_id,
            task_id=task_id,
            question=question,
            blocking_reason=blocking_reason,
            options=options or [],
        )
        self._pending[request_id] = pending

        loop = asyncio.get_running_loop()
        fut: asyncio.Future[dict[str, Any]] = loop.create_future()
        self._waiters[request_id] = fut

        # Set default timeout
        timer = loop.call_later(self.default_timeout_s, self._on_timeout, request_id)
        self._timers[request_id] = timer

        if self.on_question_created:
            try:
                res = self.on_question_created(pending)
                if asyncio.iscoroutine(res):
                    asyncio.create_task(res)
            except Exception as e:
                logger.error(f"Error in on_question_created callback: {e}")

        try:
            return await fut
        finally:
            self._cleanup(request_id)

    def answer_question(self, question_id: str, answer: str) -> bool:
        """Coordinator answers the question."""
        pending = self._pending.get(question_id)
        fut = self._waiters.get(question_id)
        if not pending or not fut or fut.done():
            return False

        pending.answer = answer
        fut.set_result({"confirmed": True, "value": answer})
        return True

    def escalate_to_user(self, question_id: str) -> bool:
        """Escalate to user, extending timeout."""
        pending = self._pending.get(question_id)
        if not pending or pending.cancelled or pending.answer is not None:
            return False

        pending.escalated = True
        timer = self._timers.get(question_id)
        if timer:
            timer.cancel()

        loop = asyncio.get_running_loop()
        new_timer = loop.call_later(self.user_timeout_s, self._on_timeout, question_id)
        self._timers[question_id] = new_timer
        return True

    def cancel_question(self, question_id: str) -> bool:
        """Cancel or abort a question."""
        pending = self._pending.get(question_id)
        fut = self._waiters.get(question_id)
        if not pending or not fut or fut.done():
            return False

        pending.cancelled = True
        fut.set_result({"cancelled": True})
        return True

    def _on_timeout(self, question_id: str) -> None:
        pending = self._pending.get(question_id)
        fut = self._waiters.get(question_id)
        if pending and fut and not fut.done():
            pending.cancelled = True
            fut.set_result({"cancelled": True, "timeout": True})

    def _cleanup(self, question_id: str) -> None:
        timer = self._timers.pop(question_id, None)
        if timer:
            timer.cancel()
        self._waiters.pop(question_id, None)

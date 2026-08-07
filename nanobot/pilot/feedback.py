"""Transport-neutral feedback processing service."""

from __future__ import annotations

import time
import uuid
from typing import TYPE_CHECKING

from nanobot.bus.events import FeedbackAck, FeedbackAction, InboundMessage
from nanobot.pilot.identity import IdentityHasher
from nanobot.pilot.store import SQLitePilotStore
from nanobot.pilot.types import CapturePriority, QueueEvent

if TYPE_CHECKING:
    from nanobot.bus.queue import MessageBus


class FeedbackService:
    """Service handling feedback authorization, storage, and re-execution."""

    def __init__(
        self,
        store: SQLitePilotStore,
        hasher: IdentityHasher,
        bus: MessageBus | None = None,
    ) -> None:
        self.store = store
        self.hasher = hasher
        self.bus = bus

    async def handle_action(self, action: FeedbackAction) -> FeedbackAck:
        """Authorize turn ownership, record feedback, and trigger re-execution if requested."""
        ownership = self.store.get_ownership(action.turn_id)
        if not ownership:
            return FeedbackAck(
                action_id=action.action_id,
                turn_id=action.turn_id,
                accepted=False,
                reason="turn_not_found",
            )

        owner_user_pseudo, owner_sess_pseudo = ownership
        expected_user_pseudo = self.hasher.hash_identity(
            "user", f"{action.channel}:{action.sender_id}"
        )
        if owner_user_pseudo != expected_user_pseudo:
            return FeedbackAck(
                action_id=action.action_id,
                turn_id=action.turn_id,
                accepted=False,
                reason="ownership_denied",
            )

        if action.kind not in {"helpful", "incorrect", "retry", "explain_more"}:
            return FeedbackAck(
                action_id=action.action_id,
                turn_id=action.turn_id,
                accepted=False,
                reason="invalid_kind",
            )

        now_ms = int(time.time() * 1000)

        # Append feedback record to SQLite store
        event = QueueEvent(
            event_id=action.action_id or uuid.uuid4().hex,
            priority=CapturePriority.FEEDBACK,
            kind="feedback",
            payload={
                "turn_id": action.turn_id,
                "user_pseudonym": owner_user_pseudo,
                "kind": action.kind,
                "metadata": action.metadata,
            },
            created_at_ms=now_ms,
        )
        self.store.write_batch([event])

        # If action requires re-execution, publish InboundMessage to bus
        if action.kind in {"retry", "explain_more"} and self.bus:
            prompt = (
                "Please retry your previous turn."
                if action.kind == "retry"
                else "Can you explain your previous response in more detail?"
            )
            inbound = InboundMessage(
                channel=action.channel,
                sender_id=action.sender_id,
                chat_id=action.chat_id,
                content=prompt,
                metadata={"retry_of_turn_id": action.turn_id, "feedback_kind": action.kind},
            )
            await self.bus.publish_inbound(inbound)

        return FeedbackAck(
            action_id=action.action_id,
            turn_id=action.turn_id,
            accepted=True,
        )

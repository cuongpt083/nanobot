"""Distillation capture hook for recording telemetry and trace artifacts."""

from __future__ import annotations

import time
import uuid

from loguru import logger

from nanobot.agent.hook import AgentHook, AgentRunHookContext, AgentTurnHookContext
from nanobot.pilot.consent import ConsentGate
from nanobot.pilot.identity import IdentityHasher
from nanobot.pilot.metrics import pilot_metrics
from nanobot.pilot.queue import CaptureQueue
from nanobot.pilot.redaction import Redactor
from nanobot.pilot.store import SQLitePilotStore
from nanobot.pilot.types import CapturePriority, QueueEvent


class DistillationCaptureHook(AgentHook):
    """Isolated turn lifecycle hook for distillation capture."""

    def __init__(
        self,
        turn_context: AgentTurnHookContext,
        queue: CaptureQueue,
        hasher: IdentityHasher,
        redactor: Redactor,
        consent_gate: ConsentGate,
        store: SQLitePilotStore,
    ) -> None:
        super().__init__(reraise=False)
        self.turn_context = turn_context
        self.queue = queue
        self.hasher = hasher
        self.redactor = redactor
        self.consent_gate = consent_gate
        self.store = store

    async def after_run(self, context: AgentRunHookContext) -> None:
        try:
            await self._process_turn_capture(context)
        except Exception as ex:
            pilot_metrics.inc_hook_error()
            logger.warning(f"DistillationCaptureHook error in after_run: {ex}")

    async def on_error(self, context: AgentRunHookContext) -> None:
        try:
            await self._process_turn_capture(context)
        except Exception as ex:
            pilot_metrics.inc_hook_error()
            logger.warning(f"DistillationCaptureHook error in on_error: {ex}")

    async def _process_turn_capture(self, context: AgentRunHookContext) -> None:
        turn_id = self.turn_context.turn_id or uuid.uuid4().hex
        channel = self.turn_context.channel
        sender_id = self.turn_context.sender_id or self.turn_context.chat_id
        session_key = self.turn_context.session_key or "default"

        user_pseudo = self.hasher.hash_identity("user", f"{channel}:{sender_id}")
        sess_pseudo = self.hasher.hash_identity("session", session_key)

        consent_state = self.store.get_consent(user_pseudo)
        provider_policy = (
            self.turn_context.provider_config.get("capture_policy", "metrics_only")
            if self.turn_context.provider_config
            else "metrics_only"
        )

        decision = self.consent_gate.evaluate(consent_state, provider_policy)
        now_ms = int(time.time() * 1000)

        # 1. Enqueue turn record
        turn_event = QueueEvent(
            event_id=uuid.uuid4().hex,
            priority=CapturePriority.FINAL,
            kind="turn",
            payload={
                "turn_id": turn_id,
                "user_pseudonym": user_pseudo,
                "session_pseudonym": sess_pseudo,
                "channel": channel,
                "chat_id": self.turn_context.chat_id,
                "consent_version": consent_state.product_version if consent_state else "pilot-v1",
                "routing_decision": self.turn_context.routing_decision or {},
                "store_prompt": decision.store_prompt,
                "store_reasoning": decision.store_reasoning,
                "store_answer": decision.store_answer,
                "training_eligible": decision.training_eligible,
            },
            created_at_ms=now_ms,
        )
        await self.queue.put(turn_event)

        # 2. Enqueue artifact record if content capture is approved
        if decision.store_prompt or decision.store_answer or decision.store_reasoning:
            prompt_raw = context.messages[0].get("content") if context.messages else ""
            answer_raw = context.final_content or ""

            r_prompt = self.redactor.redact_string(str(prompt_raw)) if decision.store_prompt else None
            r_answer = self.redactor.redact_string(str(answer_raw)) if decision.store_answer else None

            artifact_event = QueueEvent(
                event_id=uuid.uuid4().hex,
                priority=CapturePriority.ARTIFACT,
                kind="artifact",
                payload={
                    "turn_id": turn_id,
                    "prompt_text": r_prompt.data if r_prompt else None,
                    "reasoning_text": None,
                    "answer_text": r_answer.data if r_answer else None,
                    "prompt_chars": len(str(prompt_raw)),
                    "answer_chars": len(answer_raw),
                    "consent_version": consent_state.product_version if consent_state else "pilot-v1",
                    "redaction_version": "pilot-v1",
                    "capture_policy": provider_policy,
                },
                created_at_ms=now_ms,
            )
            await self.queue.put(artifact_event)

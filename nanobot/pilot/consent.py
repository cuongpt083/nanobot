"""Three-gate consent evaluation logic (Operator, User, Provider)."""

from __future__ import annotations

from typing import Literal, Optional

from nanobot.pilot.types import CaptureDecision, ConsentState

CapturePolicy = Literal["metrics_only", "answer", "reasoning"]


class ConsentGate:
    """Evaluates 3 consent gates to return a CaptureDecision."""

    def __init__(self, operator_enabled: bool) -> None:
        self.operator_enabled = operator_enabled

    def evaluate(
        self,
        consent_state: Optional[ConsentState],
        provider_policy: CapturePolicy,
    ) -> CaptureDecision:
        """Evaluate operator, user consent, and provider capture policy."""
        if not self.operator_enabled:
            return CaptureDecision(
                store_prompt=False,
                store_reasoning=False,
                store_answer=False,
                training_eligible=False,
            )

        if provider_policy == "metrics_only":
            return CaptureDecision(
                store_prompt=False,
                store_reasoning=False,
                store_answer=False,
                training_eligible=False,
            )

        product_ok = bool(consent_state and consent_state.product_allowed)
        training_ok = bool(consent_state and consent_state.training_allowed)

        store_prompt = product_ok
        store_answer = product_ok
        store_reasoning = product_ok if provider_policy == "reasoning" else False
        training_eligible = product_ok and training_ok

        return CaptureDecision(
            store_prompt=store_prompt,
            store_reasoning=store_reasoning,
            store_answer=store_answer,
            training_eligible=training_eligible,
        )

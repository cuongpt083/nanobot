"""Tests for ConsentGate evaluation logic."""

import pytest

from nanobot.pilot.consent import ConsentGate
from nanobot.pilot.types import ConsentState


def make_consent(product: bool, training: bool) -> ConsentState:
    return ConsentState(
        user_pseudonym="user_hash_123",
        product_allowed=product,
        product_version="pilot-product-v1",
        training_allowed=training,
        training_version="pilot-training-v1",
        created_at_ms=1000,
        updated_at_ms=1000,
    )


@pytest.mark.parametrize("operator_enabled", [True, False])
@pytest.mark.parametrize(
    "product_allowed,training_allowed",
    [
        (True, True),
        (True, False),
        (False, True),
        (False, False),
    ],
)
@pytest.mark.parametrize("provider_policy", ["metrics_only", "answer", "reasoning"])
def test_consent_gate_permutations(
    operator_enabled: bool,
    product_allowed: bool,
    training_allowed: bool,
    provider_policy: str,
) -> None:
    gate = ConsentGate(operator_enabled=operator_enabled)
    consent = make_consent(product_allowed, training_allowed)
    decision = gate.evaluate(consent, provider_policy)  # type: ignore

    if not operator_enabled or provider_policy == "metrics_only" or not product_allowed:
        assert decision.store_prompt is False
        assert decision.store_answer is False
        assert decision.store_reasoning is False
        assert decision.training_eligible is False
    else:
        assert decision.store_prompt is True
        assert decision.store_answer is True
        if provider_policy == "reasoning":
            assert decision.store_reasoning is True
        else:
            assert decision.store_reasoning is False

        if training_allowed:
            assert decision.training_eligible is True
        else:
            assert decision.training_eligible is False


def test_missing_user_consent() -> None:
    gate = ConsentGate(operator_enabled=True)
    decision = gate.evaluate(None, "reasoning")
    assert decision.store_prompt is False
    assert decision.store_reasoning is False
    assert decision.store_answer is False
    assert decision.training_eligible is False

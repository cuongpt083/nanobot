"""Shared types and data structures for pilot capture, privacy, store, and retention."""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any


class CapturePriority(enum.IntEnum):
    """Ordering enum for the capture queue (lower value = higher priority)."""

    CONSENT = 0
    FEEDBACK = 1
    FINAL = 2
    ATTEMPT = 3
    ARTIFACT = 4


@dataclass(frozen=True, slots=True)
class CaptureDecision:
    """Per-field capture flags after three-gate consent evaluation."""

    store_prompt: bool
    store_reasoning: bool
    store_answer: bool
    training_eligible: bool


@dataclass(frozen=True, slots=True)
class ConsentState:
    """Per-user consent state snapshot."""

    user_pseudonym: str
    product_allowed: bool
    product_version: str
    training_allowed: bool
    training_version: str
    created_at_ms: int
    updated_at_ms: int


@dataclass(frozen=True, slots=True)
class RedactionResult:
    """Result of redacting content."""

    data: Any
    rule_codes: set[str] = field(default_factory=set)


@dataclass(frozen=True, slots=True)
class QueueEvent:
    """Immutable event record for the capture queue."""

    event_id: str
    priority: CapturePriority
    kind: str
    payload: dict[str, Any]
    created_at_ms: int

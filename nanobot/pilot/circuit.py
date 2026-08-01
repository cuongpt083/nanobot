"""Thread-safe, model-scoped circuit breaking for pilot provider attempts."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from threading import Lock
from typing import Literal

CircuitState = Literal["closed", "open", "half_open"]
ALL_CANDIDATES_UNAVAILABLE = "The requested model is temporarily unavailable. Please try again later."


@dataclass(frozen=True, slots=True)
class CircuitKey:
    """A circuit identity containing only provider routing metadata."""

    provider_alias: str
    model: str


def circuit_key_for_preset(preset: object, config: object | None = None) -> CircuitKey:
    """Build a provider/model key using the same provider resolution as routing."""
    provider = getattr(preset, "provider", "auto")
    model = str(getattr(preset, "model"))
    if provider == "auto" and config is not None and hasattr(config, "get_provider_name"):
        provider = config.get_provider_name(model, preset=preset) or provider
    return CircuitKey(str(provider), model)


@dataclass(slots=True)
class _CircuitRecord:
    consecutive_failures: int = 0
    opened_at: float | None = None
    probe_in_flight: bool = False


class CircuitRegistry:
    """Track provider/model availability without retaining request content."""

    def __init__(
        self,
        clock: Callable[[], float] = time.monotonic,
        failure_threshold: int = 3,
        cooldown_seconds: float = 60.0,
    ) -> None:
        if failure_threshold < 1:
            raise ValueError("failure_threshold must be at least 1")
        if cooldown_seconds < 0:
            raise ValueError("cooldown_seconds must not be negative")
        self._clock = clock
        self._failure_threshold = failure_threshold
        self._cooldown_seconds = cooldown_seconds
        self._records: dict[CircuitKey, _CircuitRecord] = {}
        self._lock = Lock()

    def allow(self, key: CircuitKey) -> bool:
        """Return whether an attempt is admitted, reserving a half-open probe."""
        with self._lock:
            record = self._records.get(key)
            if record is None or record.opened_at is None:
                return True
            if not self._cooldown_elapsed(record):
                return False
            if record.probe_in_flight:
                return False
            record.probe_in_flight = True
            return True

    def record_success(self, key: CircuitKey) -> None:
        """Close the circuit and reset its failure count after a successful attempt."""
        with self._lock:
            self._records[key] = _CircuitRecord()

    def record_failure(self, key: CircuitKey, error_class: str | None) -> None:
        """Record one failed attempt, opening authentication failures immediately."""
        with self._lock:
            record = self._records.setdefault(key, _CircuitRecord())
            now = self._clock()
            record.consecutive_failures += 1
            if self._is_authentication_error(error_class) or record.probe_in_flight:
                record.opened_at = now
                record.probe_in_flight = False
                return
            if record.consecutive_failures >= self._failure_threshold:
                record.opened_at = now
                record.probe_in_flight = False

    def snapshot(self) -> dict[CircuitKey, dict[str, CircuitState | int | bool]]:
        """Return a copy of circuit state keyed only by provider alias and model."""
        with self._lock:
            return {
                key: {
                    "state": self._state(record),
                    "failures": record.consecutive_failures,
                    "probe_in_flight": record.probe_in_flight,
                }
                for key, record in self._records.items()
            }

    def _cooldown_elapsed(self, record: _CircuitRecord) -> bool:
        return record.opened_at is not None and self._clock() - record.opened_at >= self._cooldown_seconds

    def _state(self, record: _CircuitRecord) -> CircuitState:
        if record.opened_at is None:
            return "closed"
        return "half_open" if self._cooldown_elapsed(record) else "open"

    @staticmethod
    def _is_authentication_error(error_class: str | None) -> bool:
        normalized = (error_class or "").strip().lower()
        return any(token in normalized for token in ("auth", "credential", "permission", "unauthorized"))

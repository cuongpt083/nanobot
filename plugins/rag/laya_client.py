"""Resilient asynchronous client for the Laya Decision Service with Circuit Breaker."""

from __future__ import annotations

import logging
import time
from typing import Any, Tuple
import httpx

logger = logging.getLogger(__name__)


class LayaClient:
    """Fast System 1 gating client for evaluating if a query requires knowledge retrieval."""

    def __init__(
        self,
        service_url: str = "http://localhost:8000/v1/decide",
        threshold: float = 0.70,
        timeout: float = 0.50,
        failure_threshold: int = 3,
        cooldown_seconds: float = 30.0,
        enabled: bool = True,
    ) -> None:
        self.service_url = service_url
        self.threshold = threshold
        self.timeout = timeout
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self.enabled = enabled
        self.consecutive_failures = 0
        self.last_failure_time = 0.0

    @property
    def circuit_status(self) -> str:
        if not self.enabled:
            return "disabled"
        if self.consecutive_failures >= self.failure_threshold:
            if time.time() - self.last_failure_time < self.cooldown_seconds:
                return "open"
            # Half-open probe
            return "half-open"
        return "closed"

    def record_success(self) -> None:
        self.consecutive_failures = 0

    def record_failure(self) -> None:
        self.consecutive_failures += 1
        self.last_failure_time = time.time()

    async def should_retrieve(
        self,
        query: str,
        workspace: str = "",
        threshold: float | None = None,
    ) -> Tuple[bool, float, str]:
        """Evaluate whether `query` requires external knowledge retrieval.

        Returns (should_retrieve, confidence, status_reason).
        Fail-soft guarantee: on circuit open, network failure, or timeout,
        returns True to allow retrieval without blocking user workflow.
        """
        if not self.enabled:
            return True, 1.0, "laya_disabled"

        query_str = (query or "").strip()
        if not query_str:
            return False, 0.0, "empty_query"

        status = self.circuit_status
        if status == "open":
            logger.warning("Laya circuit is OPEN. Bypassing decision gating.")
            return True, 1.0, "circuit_open_bypass"

        thresh = threshold if threshold is not None else self.threshold
        payload = {
            "user_message": query_str,
            "knowledge_bases": [workspace or "default"],
            "threshold": thresh,
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(self.service_url, json=payload)
                if resp.status_code == 200:
                    self.record_success()
                    data: dict[str, Any] = resp.json()
                    should_preseed = bool(data.get("should_preseed", True))
                    conf = float(data.get("confidence", 0.0))
                    return should_preseed, conf, "evaluated"

                logger.warning("Laya returned status %d: %s", resp.status_code, resp.text[:200])
                self.record_failure()
                return True, 0.0, f"http_error_{resp.status_code}"
        except httpx.TimeoutException:
            logger.warning("Laya decision timed out (>%.2fs). Bypassing to LightRAG.", self.timeout)
            self.record_failure()
            return True, 0.0, "timeout_bypass"
        except Exception as exc:
            logger.warning("Laya connection failed: %s. Bypassing to LightRAG.", exc)
            self.record_failure()
            return True, 0.0, "error_bypass"

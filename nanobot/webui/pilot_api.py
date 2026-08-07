"""HTTP handlers for /api/pilot/health and /api/pilot/metrics endpoints."""

from __future__ import annotations

import json
from typing import Any


async def handle_pilot_health_request(health_service: Any) -> tuple[int, bytes, str]:
    """Handle GET /api/pilot/health requests."""
    if not health_service:
        payload = json.dumps({"status": "disabled"}).encode("utf-8")
        return 200, payload, "application/json"

    snapshot = await health_service.get_health_snapshot()
    code = 200 if snapshot.get("status") == "ok" else 503
    payload = json.dumps(snapshot).encode("utf-8")
    return code, payload, "application/json"


async def handle_pilot_metrics_request(pilot_service: Any) -> tuple[int, bytes, str]:
    """Handle GET /api/pilot/metrics requests."""
    if not pilot_service:
        payload = json.dumps({"error": "pilot service not configured"}).encode("utf-8")
        return 404, payload, "application/json"

    health = await pilot_service.health_snapshot()
    payload = json.dumps(health).encode("utf-8")
    return 200, payload, "application/json"

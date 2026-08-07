"""Tests for /api/pilot/health and /api/pilot/metrics endpoints."""

import json
from unittest.mock import AsyncMock

import pytest

from nanobot.webui.pilot_api import (
    handle_pilot_health_request,
    handle_pilot_metrics_request,
)


@pytest.mark.asyncio
async def test_pilot_health_request() -> None:
    service_mock = AsyncMock()
    service_mock.get_health_snapshot.return_value = {
        "status": "ok",
        "agent": {"status": "ok"},
    }

    code, body, content_type = await handle_pilot_health_request(service_mock)
    assert code == 200
    assert content_type == "application/json"
    data = json.loads(body.decode("utf-8"))
    assert data["status"] == "ok"


@pytest.mark.asyncio
async def test_pilot_metrics_request() -> None:
    service_mock = AsyncMock()
    service_mock.health_snapshot.return_value = {
        "status": "ok",
        "accepted_total": 10,
    }

    code, body, content_type = await handle_pilot_metrics_request(service_mock)
    assert code == 200
    data = json.loads(body.decode("utf-8"))
    assert data["accepted_total"] == 10

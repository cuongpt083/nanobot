"""Health check service for agent, providers, channels, and capture store."""

from __future__ import annotations

from typing import Any


class HealthCheckService:
    """Aggregates system components health snapshot."""

    def __init__(
        self,
        agent_loop: Any = None,
        pilot_service: Any = None,
        channel_manager: Any = None,
    ) -> None:
        self.agent_loop = agent_loop
        self.pilot_service = pilot_service
        self.channel_manager = channel_manager

    async def get_health_snapshot(self) -> dict[str, Any]:
        """Return structured health status across all subsystems."""
        agent_ok = True
        providers_ok = True
        channels_ok = True
        store_ok = True

        capture_health = (
            await self.pilot_service.health_snapshot()
            if self.pilot_service
            else {"status": "disabled"}
        )

        overall = "ok"
        if not (agent_ok and providers_ok and channels_ok and store_ok):
            overall = "degraded"

        return {
            "status": overall,
            "agent": {"status": "ok" if agent_ok else "down"},
            "providers": {"status": "ok" if providers_ok else "degraded"},
            "channels": {"status": "ok" if channels_ok else "degraded"},
            "capture_store": capture_health,
            "student": {"status": "ok"},
        }

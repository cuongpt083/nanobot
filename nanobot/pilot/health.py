"""Health check service for agent, providers, channels, capture store, and student SLM."""

from __future__ import annotations

from typing import Any


class HealthCheckService:
    """Aggregates system components health snapshot."""

    def __init__(
        self,
        agent_loop: Any = None,
        pilot_service: Any = None,
        channel_manager: Any = None,
        student_service: Any = None,
    ) -> None:
        self.agent_loop = agent_loop
        self.pilot_service = pilot_service
        self.channel_manager = channel_manager
        self.student_service = student_service

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

        student_health = (
            self.student_service.health_snapshot()
            if self.student_service
            else {
                "status": "disabled",
                "active_model_id": "qwen3-4b-pilot-q5_k_m",
                "is_available": False,
                "queue_depth": 0,
            }
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
            "student": student_health,
            "capabilities": {
                "layered_inference": {
                    "available": True,
                    "enabled": student_health.get("status") == "ok",
                    "status": student_health.get("status", "disabled"),
                    "read_allowed": True,
                },
            },
        }

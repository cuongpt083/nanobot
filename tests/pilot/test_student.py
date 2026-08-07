"""Tests for StudentInferenceService."""

import pytest

from nanobot.pilot.student import StudentInferenceService, StudentUnavailableError


def test_student_inference_service_unavailable() -> None:
    service = StudentInferenceService(active_model_id="nonexistent.gguf")
    assert not service.is_available
    snapshot = service.health_snapshot()
    assert snapshot["status"] == "degraded"
    assert snapshot["is_available"] is False

    with pytest.raises(StudentUnavailableError):
        service.generate(prompt="Hello")

    with pytest.raises(StudentUnavailableError):
        list(service.generate_stream(prompt="Hello"))

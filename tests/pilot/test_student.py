"""Tests for StudentInferenceService."""

from nanobot.pilot.student import StudentInferenceService


def test_student_inference_service_fallback() -> None:
    service = StudentInferenceService(model_path="nonexistent.gguf")
    res = service.generate(prompt="Hello")

    assert "text" in res
    assert "usage" in res
    assert res["stop_reason"] == "stop"


def test_student_inference_streaming() -> None:
    service = StudentInferenceService(model_path="nonexistent.gguf")
    chunks = list(service.generate_stream(prompt="Hello"))

    assert len(chunks) == 1
    assert "content_delta" in chunks[0]

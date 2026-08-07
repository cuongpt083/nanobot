"""Tests for StudentProvider."""

from unittest.mock import MagicMock

import pytest

from nanobot.pilot.student import StudentInferenceService
from nanobot.providers.student_provider import StudentProvider


@pytest.mark.asyncio
async def test_student_provider_chat_unavailable() -> None:
    provider = StudentProvider(active_model_id="nonexistent-model-id")
    messages = [{"role": "user", "content": "What is 2+2?"}]
    response = await provider.chat(messages=messages)

    assert response is not None
    assert response.finish_reason == "error"
    assert "Error:" in response.content


@pytest.mark.asyncio
async def test_student_provider_chat_mocked() -> None:
    mock_service = MagicMock(spec=StudentInferenceService)
    mock_service.generate.return_value = {
        "text": "2+2 is 4",
        "usage": {"prompt_tokens": 5, "completion_tokens": 4},
        "stop_reason": "stop",
    }
    provider = StudentProvider(student_service=mock_service)
    messages = [{"role": "user", "content": "What is 2+2?"}]
    response = await provider.chat(messages=messages)

    assert response.content == "2+2 is 4"
    assert response.finish_reason == "stop"
    assert response.usage == {"prompt_tokens": 5, "completion_tokens": 4}


@pytest.mark.asyncio
async def test_student_provider_chat_stream_mocked() -> None:
    mock_service = MagicMock(spec=StudentInferenceService)
    mock_service.generate_stream.return_value = [
        {"content_delta": "2+2 ", "stop_reason": None, "usage": None},
        {"content_delta": "is 4", "stop_reason": "stop", "usage": {"prompt_tokens": 5, "completion_tokens": 4}},
    ]
    provider = StudentProvider(student_service=mock_service)
    messages = [{"role": "user", "content": "What is 2+2?"}]

    deltas: list[str] = []

    async def on_delta(d: str) -> None:
        deltas.append(d)

    response = await provider.chat_stream(messages=messages, on_content_delta=on_delta)

    assert deltas == ["2+2 ", "is 4"]
    assert response.content == "2+2 is 4"
    assert response.finish_reason == "stop"

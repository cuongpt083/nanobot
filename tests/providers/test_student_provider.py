"""Tests for StudentProvider."""

import pytest

from nanobot.providers.student_provider import StudentProvider


@pytest.mark.asyncio
async def test_student_provider_chat() -> None:
    provider = StudentProvider(model_path="nonexistent.gguf")
    messages = [{"role": "user", "content": "What is 2+2?"}]
    response = await provider.chat(messages=messages)

    assert response is not None
    assert response.content is not None
    assert response.finish_reason == "stop"
    assert "usage" in response.__dict__ or hasattr(response, "usage")

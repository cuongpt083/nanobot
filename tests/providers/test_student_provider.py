"""Tests for StudentProvider."""

import pytest
from nanobot.providers.student_provider import StudentProvider


@pytest.mark.asyncio
async def test_student_provider_generate() -> None:
    provider = StudentProvider()
    res = await provider.chat(messages=[{"role": "user", "content": "What is 2+2?"}])

    assert res.content is not None
    assert res.content != ""
    assert res.finish_reason == "stop"

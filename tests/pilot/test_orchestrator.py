"""Tests for TeacherStudentOrchestrator."""

import pytest

from nanobot.pilot.orchestrator import TeacherStudentOrchestrator
from nanobot.pilot.student import StudentInferenceService


@pytest.mark.asyncio
async def test_orchestrate_simple_path() -> None:
    student = StudentInferenceService(model_path="nonexistent.gguf")
    orchestrator = TeacherStudentOrchestrator(student_service=student)

    res = await orchestrator.process_request("Hi there")
    assert res["route"] == "student_direct"
    assert "answer" in res

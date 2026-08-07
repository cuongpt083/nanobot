"""Tests for TeacherStudentOrchestrator."""

from unittest.mock import MagicMock

import pytest

from nanobot.pilot.orchestrator import TeacherStudentOrchestrator
from nanobot.pilot.student import StudentInferenceService
from nanobot.providers.base import LLMProvider, LLMResponse


class MockTeacherProvider(LLMProvider):
    def get_default_model(self) -> str:
        return "mock-teacher"

    async def chat(self, messages, **kwargs) -> LLMResponse:
        return LLMResponse(content="Teacher Answer", finish_reason="stop")


@pytest.mark.asyncio
async def test_orchestrate_simple_path_available() -> None:
    mock_student = MagicMock(spec=StudentInferenceService)
    mock_student.is_available = True
    mock_student.generate.return_value = {"text": "Simple Answer", "usage": {"prompt_tokens": 2, "completion_tokens": 2}}

    orchestrator = TeacherStudentOrchestrator(student_service=mock_student)
    res = await orchestrator.process_request("Hi there")

    assert res["route"] == "student_direct"
    assert res["answer"] == "Simple Answer"


@pytest.mark.asyncio
async def test_orchestrate_simple_path_unavailable_fallback() -> None:
    mock_student = MagicMock(spec=StudentInferenceService)
    mock_student.is_available = False

    teacher = MockTeacherProvider()
    orchestrator = TeacherStudentOrchestrator(student_service=mock_student, teacher_provider=teacher)

    res = await orchestrator.process_request("Hi there")
    assert res["route"] == "teacher_fallback"
    assert res["answer"] == "Teacher Answer"


@pytest.mark.asyncio
async def test_orchestrate_complex_path_teacher_direct() -> None:
    mock_student = MagicMock(spec=StudentInferenceService)
    mock_student.is_available = True

    teacher = MockTeacherProvider()
    orchestrator = TeacherStudentOrchestrator(student_service=mock_student, teacher_provider=teacher)

    res = await orchestrator.process_request("Write a python function ```def foo(): pass```")
    assert res["route"] == "teacher_direct"
    assert res["answer"] == "Teacher Answer"
    # Ensure student was NOT called for complex query
    mock_student.generate.assert_not_called()

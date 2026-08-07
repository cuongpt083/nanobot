"""Tests for TeacherStudentOrchestrator."""

import pytest

from nanobot.pilot.orchestrator import TeacherStudentOrchestrator
from nanobot.pilot.student import StudentInferenceService
from nanobot.providers.base import LLMProvider, LLMResponse


class MockTeacherProvider(LLMProvider):
    def __init__(self, review_decision: str = "approved") -> None:
        super().__init__()
        self.review_decision = review_decision

    def get_default_model(self) -> str:
        return "mock-teacher"

    async def chat(self, messages, **kwargs) -> LLMResponse:
        content = f'{{"decision": "{self.review_decision}", "reasoning": "Mock evaluation"}}'
        return LLMResponse(content=content, finish_reason="stop")


@pytest.mark.asyncio
async def test_orchestrate_simple_path() -> None:
    student = StudentInferenceService(model_path="nonexistent.gguf")
    orchestrator = TeacherStudentOrchestrator(student_service=student)

    res = await orchestrator.process_request("Hi there")
    assert res["route"] == "student_direct"
    assert "answer" in res


@pytest.mark.asyncio
async def test_orchestrate_complex_path_approved() -> None:
    student = StudentInferenceService(model_path="nonexistent.gguf")
    teacher = MockTeacherProvider(review_decision="approved")
    orchestrator = TeacherStudentOrchestrator(student_service=student, teacher_provider=teacher)

    res = await orchestrator.process_request("Write a python function ```def foo(): pass```")
    assert res["route"] in ("teacher_student_plan", "teacher_fallback")
    assert "answer" in res


@pytest.mark.asyncio
async def test_orchestrate_complex_path_rejected_fallback() -> None:
    student = StudentInferenceService(model_path="nonexistent.gguf")
    teacher = MockTeacherProvider(review_decision="rejected")
    orchestrator = TeacherStudentOrchestrator(student_service=student, teacher_provider=teacher)

    res = await orchestrator.process_request("Write a python function ```def foo(): pass```")
    assert res["route"] == "teacher_fallback"
    assert "answer" in res

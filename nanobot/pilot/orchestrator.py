"""Teacher-Student orchestrator for Layered Student Routing and Teacher Fallback."""

from __future__ import annotations

from typing import Any

from nanobot.pilot.complexity import TaskComplexityClassifier
from nanobot.pilot.student import StudentInferenceService, StudentUnavailableError
from nanobot.providers.base import LLMProvider


class TeacherStudentOrchestrator:
    """Orchestrates layered routing between student SLM and teacher LLM."""

    def __init__(
        self,
        student_service: StudentInferenceService,
        teacher_provider: LLMProvider | None = None,
        classifier: TaskComplexityClassifier | None = None,
    ) -> None:
        self.student = student_service
        self.teacher = teacher_provider
        self.classifier = classifier or TaskComplexityClassifier()

    async def process_request(
        self,
        message: str,
        required_tools: list[str] | None = None,
        has_media: bool = False,
    ) -> dict[str, Any]:
        """Route request to Student or Teacher based on task complexity."""
        complexity, score = self.classifier.classify(
            message,
            required_tools=required_tools,
            has_media=has_media,
        )

        if complexity == "simple" and self.student.is_available:
            try:
                res = self.student.generate(message)
                return {
                    "route": "student_direct",
                    "answer": res["text"],
                    "complexity_score": score,
                    "usage": res.get("usage", {}),
                }
            except StudentUnavailableError:
                pass  # Fallback to teacher

        # Complex or Student Unavailable path -> Direct to Teacher
        if self.teacher:
            teacher_res = await self.teacher.chat(messages=[{"role": "user", "content": message}])
            return {
                "route": "teacher_direct" if complexity == "complex" else "teacher_fallback",
                "answer": teacher_res.content or "",
                "complexity_score": score,
                "usage": getattr(teacher_res, "usage", {}),
            }

        return {
            "route": "error",
            "answer": "Error: Neither student nor teacher provider is available.",
            "complexity_score": score,
            "usage": {},
        }

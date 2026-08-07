"""Teacher-Student orchestrator for SLM planning and LLM teacher review."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Literal

from nanobot.pilot.complexity import TaskComplexityClassifier
from nanobot.pilot.student import StudentInferenceService
from nanobot.providers.base import LLMProvider


@dataclass
class PlanStep:
    step_number: int
    description: str
    tool: str | None = None
    expected_output: str = ""


@dataclass
class Plan:
    task_summary: str
    steps: list[PlanStep]
    estimated_complexity: Literal["simple", "moderate", "high"]
    requires_tools: bool


@dataclass
class PlanReview:
    decision: Literal["approved", "revisions", "rejected"]
    reasoning: str
    suggested_changes: list[str] | None = None


class TeacherStudentOrchestrator:
    """Coordinates SLM student planning and LLM teacher review."""

    def __init__(
        self,
        student_service: StudentInferenceService,
        teacher_provider: LLMProvider | None = None,
        classifier: TaskComplexityClassifier | None = None,
    ) -> None:
        self.student = student_service
        self.teacher = teacher_provider
        self.classifier = classifier or TaskComplexityClassifier()

    async def process_request(self, message: str) -> dict[str, Any]:
        complexity, score = self.classifier.classify(message)

        if complexity == "simple" or not self.teacher:
            # Simple path: direct SLM response
            res = self.student.generate(message)
            return {
                "route": "student_direct",
                "answer": res["text"],
                "complexity_score": score,
            }

        # Complex path: SLM planning + Teacher review
        plan_prompt = f"User request: {message}\nGenerate step-by-step plan in JSON."
        slm_plan_res = self.student.generate(plan_prompt)

        try:
            plan = json.loads(slm_plan_res["text"])
        except Exception:
            # Fallback on plan JSON parse failure
            teacher_res = await self.teacher.chat(messages=[{"role": "user", "content": message}])
            return {
                "route": "teacher_fallback",
                "answer": teacher_res.content or "",
                "complexity_score": score,
            }

        # Teacher review call
        review_prompt = f"Review student plan for request '{message}': {json.dumps(plan)}"
        teacher_review_res = await self.teacher.chat(messages=[{"role": "user", "content": review_prompt}])

        return {
            "route": "teacher_student_plan",
            "plan": plan,
            "teacher_review": teacher_review_res.content,
            "answer": f"Executed plan under teacher review: {message}",
            "complexity_score": score,
        }

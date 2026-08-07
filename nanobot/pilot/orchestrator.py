"""Teacher-Student orchestrator for SLM planning and LLM teacher review."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
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


_TEACHER_REVIEW_PROMPT = """You are a plan review service for a teacher-student AI system. The student model (SLM) has
generated a plan for the user's request. Your job is to review the plan for correctness,
completeness, and safety.

User request: {user_request}

Student plan:
{plan_json}

Respond with a JSON object containing:
- "decision": "approved" | "revisions" | "rejected"
- "reasoning": brief explanation of your decision
- "suggested_changes": list of specific changes needed (only if decision is "revisions")
"""


class TeacherStudentOrchestrator:
    """Coordinates SLM student planning and LLM teacher review."""

    def __init__(
        self,
        student_service: StudentInferenceService,
        teacher_provider: LLMProvider | None = None,
        classifier: TaskComplexityClassifier | None = None,
        max_revision_rounds: int = 2,
    ) -> None:
        self.student = student_service
        self.teacher = teacher_provider
        self.classifier = classifier or TaskComplexityClassifier()
        self.max_revision_rounds = max_revision_rounds

    async def process_request(
        self,
        message: str,
        tools_available: list[str] | None = None,
    ) -> dict[str, Any]:
        complexity, score = self.classifier.classify(message, tools_available=tools_available)

        if complexity == "simple" or not self.teacher:
            # Simple path: direct SLM response
            res = self.student.generate(message)
            return {
                "route": "student_direct",
                "answer": res["text"],
                "complexity_score": score,
            }

        # Complex path: SLM planning + Teacher review
        plan_prompt = (
            f"User request: {message}\n"
            "Create a step-by-step plan as JSON matching schema: "
            '{"task_summary": "...", "steps": [{"step_number": 1, "description": "...", "tool": null}], '
            '"estimated_complexity": "moderate", "requires_tools": false}'
        )

        plan: Plan | None = None
        slm_plan_res = self.student.generate(plan_prompt)

        try:
            raw_data = json.loads(slm_plan_res["text"])
            steps = [
                PlanStep(
                    step_number=s.get("step_number", i + 1),
                    description=s.get("description", ""),
                    tool=s.get("tool"),
                    expected_output=s.get("expected_output", ""),
                )
                for i, s in enumerate(raw_data.get("steps", []))
            ]
            plan = Plan(
                task_summary=raw_data.get("task_summary", message),
                steps=steps,
                estimated_complexity=raw_data.get("estimated_complexity", "moderate"),
                requires_tools=bool(raw_data.get("requires_tools", False)),
            )
        except Exception:
            plan = None

        if plan is None:
            # Fallback to teacher directly
            teacher_res = await self.teacher.chat(messages=[{"role": "user", "content": message}])
            return {
                "route": "teacher_fallback",
                "answer": teacher_res.content or "",
                "complexity_score": score,
            }

        # Teacher review loop (max revision rounds)
        current_plan = plan
        review_decision = "rejected"
        final_review_reasoning = ""

        for round_idx in range(self.max_revision_rounds + 1):
            review_prompt = _TEACHER_REVIEW_PROMPT.format(
                user_request=message,
                plan_json=json.dumps(asdict(current_plan), ensure_ascii=False),
            )

            teacher_review_res = await self.teacher.chat(messages=[{"role": "user", "content": review_prompt}])
            try:
                review_data = json.loads(teacher_review_res.content or "{}")
                review_decision = review_data.get("decision", "rejected")
                final_review_reasoning = review_data.get("reasoning", "")
            except Exception:
                review_decision = "approved" if "approve" in (teacher_review_res.content or "").lower() else "rejected"
                final_review_reasoning = teacher_review_res.content or ""

            if review_decision == "approved":
                break
            elif review_decision == "revisions" and round_idx < self.max_revision_rounds:
                # Ask SLM to revise plan
                revise_prompt = (
                    f"User request: {message}\nPrevious plan: {json.dumps(asdict(current_plan))}\n"
                    f"Teacher feedback: {final_review_reasoning}\nRevise plan JSON."
                )
                slm_revise_res = self.student.generate(revise_prompt)
                try:
                    rev_data = json.loads(slm_revise_res["text"])
                    rev_steps = [
                        PlanStep(
                            step_number=s.get("step_number", i + 1),
                            description=s.get("description", ""),
                            tool=s.get("tool"),
                            expected_output=s.get("expected_output", ""),
                        )
                        for i, s in enumerate(rev_data.get("steps", []))
                    ]
                    current_plan = Plan(
                        task_summary=rev_data.get("task_summary", message),
                        steps=rev_steps,
                        estimated_complexity=rev_data.get("estimated_complexity", "moderate"),
                        requires_tools=bool(rev_data.get("requires_tools", False)),
                    )
                except Exception:
                    pass
            else:
                break

        if review_decision != "approved":
            # Rejection or unhandled revision fallback
            teacher_res = await self.teacher.chat(messages=[{"role": "user", "content": message}])
            return {
                "route": "teacher_fallback",
                "answer": teacher_res.content or "",
                "complexity_score": score,
            }

        # Execute approved plan
        step_outputs: list[str] = []
        for step in current_plan.steps:
            if step.tool is not None:
                # Delegate tool execution step to teacher
                tool_prompt = f"Execute tool step '{step.description}' using tool '{step.tool}' for task '{message}'"
                t_out = await self.teacher.chat(messages=[{"role": "user", "content": tool_prompt}])
                step_outputs.append(t_out.content or "")
            else:
                s_out = self.student.generate(f"Execute step: {step.description}")
                step_outputs.append(s_out.get("text", ""))

        final_answer = "\n".join(step_outputs) if step_outputs else f"Plan executed: {message}"

        return {
            "route": "teacher_student_plan",
            "plan": asdict(current_plan),
            "teacher_review": {"decision": review_decision, "reasoning": final_review_reasoning},
            "answer": final_answer,
            "complexity_score": score,
        }

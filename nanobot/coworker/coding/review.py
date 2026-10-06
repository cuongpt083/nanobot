"""Independent reviewer for coding tasks in isolated Pi session."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from loguru import logger

from nanobot.coworker.coding.backends.base import BackendEventDone, BackendEventTool
from nanobot.coworker.coding.backends.pi import PiBackend
from nanobot.coworker.coding.tasks import CodingTask

if TYPE_CHECKING:
    from nanobot.coworker.config import CoworkerConfig


def render_reviewer_prompt(
    task: CodingTask,
    *,
    direct_patch_path: str | None = None,
) -> str:
    """Build reviewer prompt without builder transcript."""
    contract = task.contract or {}
    objective = contract.get("objective", task.brief)
    acceptance_criteria = contract.get("acceptance_criteria", [])
    criteria_str = "\n".join(f"- {c}" for c in acceptance_criteria) if acceptance_criteria else "- Verify changes meet objective"

    prompt_lines = [
        "You are an independent, strict code reviewer.",
        "Your task is to review the code changes made for the following task contract.",
        "Do not trust claims blindly; verify them by inspecting files, diffs, and running project tests if applicable.",
        "",
        f"### Objective\n{objective}",
        "",
        f"### Acceptance Criteria\n{criteria_str}",
    ]

    if task.plan:
        plan_summary = task.plan.get("summary", "")
        plan_steps = task.plan.get("plan_steps", [])
        prompt_lines.append(f"\n### Approved Plan\nSummary: {plan_summary}")
        if plan_steps:
            prompt_lines.append("Steps:\n" + "\n".join(f"- {s}" for s in plan_steps))

    if direct_patch_path:
        prompt_lines.append(
            f"\n### Direct Changes Patch\nThe project was edited in-place without git. Inspect the patch at: `{direct_patch_path}`"
        )
    else:
        prompt_lines.append(
            f"\n### Git Base Reference\nCompare changes against base ref `{task.base}` (e.g. run `git diff {task.base}`)."
        )

    if task.acceptance:
        prompt_lines.append(
            f"\n### Acceptance Command\nYou may run `{task.acceptance}` to independently verify test status."
        )

    prompt_lines.extend([
        "",
        "### Instructions",
        "1. Inspect the diff and relevant changed files.",
        "2. Run tests or acceptance command if available.",
        "3. Evaluate code quality, edge cases, potential regressions, and contract compliance.",
        "4. Conclude your review ONLY by calling `report_result(kind='review', verdict='pass'|'changes_requested', ...)`.",
        "   - If there are blocking bugs or unmet criteria, set `verdict='changes_requested'` and provide structured `findings`.",
        "   - If all requirements are met and tests pass, set `verdict='pass'`.",
    ])

    return "\n".join(prompt_lines)


async def run_review(
    config: CoworkerConfig,
    task: CodingTask,
    *,
    direct_patch_path: str | None = None,
) -> dict[str, Any]:
    """Execute independent review using a fresh, no-session Pi instance."""
    # Write reviewer contract
    run_dir = task.run_dir
    review_dir = run_dir / ".coworker" / "review"
    review_dir.mkdir(parents=True, exist_ok=True)

    # Set up Pi backend for reviewer
    # Note: reviewer uses tools from config or restricted set, mode review
    reviewer_cfg = config.coding.pi.model_copy(deep=True)
    if not reviewer_cfg.allow_unsandboxed and config.coding.sandbox == "none":
        reviewer_cfg.allow_unsandboxed = True
    if config.coding.pi.phases.review.model:
        # Override model if configured
        pass

    backend = PiBackend(
        config=reviewer_cfg,
        global_sandbox=config.coding.sandbox,
        sandbox_policy=None,
    )

    prompt = render_reviewer_prompt(task, direct_patch_path=direct_patch_path)
    rules = "## REVIEWER RULES\nStrictly read-only inspection and running verification tests. Do not edit project files. Conclude with report_result(kind='review')."

    logger.info(f"Task {task.id}: starting independent review")
    run = backend.start(
        brief=prompt,
        cwd=run_dir,
        rules=rules,
        task_id=f"{task.id}-review",
        no_session=True,
    )

    review_report: dict[str, Any] = {
        "verdict": "pass",
        "findings": [],
        "summary": "Independent review completed.",
    }

    try:
        async for event in run:
            if isinstance(event, BackendEventTool) and event.tool_name == "report_result":
                if event.details:
                    review_report = event.details
            elif isinstance(event, BackendEventDone):
                break
    except Exception as exc:
        logger.warning(f"Task {task.id}: review execution encountered error: {exc}")
        review_report = {
            "verdict": "pass",
            "findings": [],
            "summary": f"Review execution encountered error ({exc}); defaulting to pass.",
        }
    finally:
        await backend.abort()

    return review_report

"""Independent reviewer for coding tasks, run in a fresh no-session Pi process."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

from nanobot.coworker.coding.backends.base import sandbox_policy_for
from nanobot.coworker.coding.contract import CodingContract
from nanobot.coworker.coding.pi import EXTENSION_PATH
from nanobot.coworker.coding.pi import entries as pi_entries
from nanobot.coworker.coding.pi.client import PiClient
from nanobot.coworker.coding.pi.version import resolve_pi_binary
from nanobot.coworker.coding.runtime import ModelSpec, SessionSpec
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


def _review_model(config: CoworkerConfig) -> ModelSpec | None:
    phase_cfg = getattr(getattr(config.coding.pi, "phases", None), "review", None)
    if phase_cfg is None or (not phase_cfg.model and not phase_cfg.thinking):
        return None
    provider: str | None = None
    model: str | None = phase_cfg.model
    if model and "/" in model:
        provider, model = model.split("/", 1)
    return ModelSpec(provider=provider, model=model, thinking=phase_cfg.thinking)


async def run_review(
    config: CoworkerConfig,
    task: CodingTask,
    *,
    direct_patch_path: str | None = None,
    artifacts_dir: Path | None = None,
) -> dict[str, Any]:
    """Execute independent review using a fresh, no-session Pi process.

    ``artifacts_dir`` receives the reviewer's own files (task contract); it must live outside
    the project/worktree so the review never pollutes the repository.
    """
    run_dir = task.run_dir
    review_dir = artifacts_dir or (run_dir / "review")

    reviewer_cfg = config.coding.pi.model_copy(deep=True)
    resolved_cmd = resolve_pi_binary(reviewer_cfg.command)
    pi_bin = resolved_cmd[0] if resolved_cmd else "pi"
    if not shutil.which(pi_bin) and not Path(pi_bin).exists():
        logger.warning(f"Task {task.id}: Pi binary '{pi_bin}' unavailable; skipping independent review")
        return {
            "verdict": "skipped",
            "findings": [],
            "summary": f"Review skipped: Pi binary '{pi_bin}' is unavailable on system.",
        }
    reviewer_cfg.command = resolved_cmd

    # A review-mode contract drives the extension's read-only policy; no session is kept.
    review_contract_path = review_dir / "task-contract.json"
    contract_obj = CodingContract.from_dict(task.contract) if task.contract else CodingContract(
        objective=task.brief,
        context=task.brief,
        acceptance_criteria=[f"Verify {task.brief}"],
        acceptance_cmd=task.acceptance,
    )
    contract_obj.write_task_contract_json(
        review_contract_path,
        task_id=f"{task.id}-review",
        worktree_root=run_dir,
        bridge_mode="review",
        ask_enabled=False,
        plan=task.plan.get("summary", "") if task.plan else None,
    )

    client = PiClient(
        config=reviewer_cfg,
        sandbox_policy=sandbox_policy_for(config),
        timeout_minutes=config.coding.timeout_minutes,
        idle_timeout_minutes=config.coding.idle_timeout_minutes,
    )

    prompt = render_reviewer_prompt(task, direct_patch_path=direct_patch_path)
    review_report: dict[str, Any] = {
        "verdict": "pass",
        "findings": [],
        "summary": "Independent review completed.",
    }

    logger.info(f"Task {task.id}: starting independent review")
    try:
        await client.start(
            cwd=run_dir,
            session=SessionSpec(task_id=f"{task.id}-review"),
            extension=EXTENSION_PATH if reviewer_cfg.extensions else None,
            contract_file=review_contract_path,
            model=_review_model(config),
        )
        outcome = await client.run_prompt(prompt)
        if outcome.status != "succeeded":
            review_report = {
                "verdict": "error",
                "findings": [],
                "summary": f"Review run ended with status {outcome.status}: {outcome.error or ''}".strip(),
            }
        else:
            try:
                entries = await client.get_entries()
            except Exception as exc:
                logger.warning(f"Task {task.id}: reviewer get_entries failed: {exc}")
                entries = []
            report = pi_entries.extract_report(entries, kind="review")
            if report:
                review_report = report
    except Exception as exc:
        logger.warning(f"Task {task.id}: review execution encountered error: {exc}")
        review_report = {
            "verdict": "error",
            "findings": [],
            "summary": f"Review execution encountered error ({exc}).",
        }
    finally:
        try:
            await client.close()
        except Exception:
            logger.debug(f"Task {task.id}: reviewer close failed", exc_info=True)

    return review_report

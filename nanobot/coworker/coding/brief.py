"""Brief and RULES rendering for coding harnesses."""

from __future__ import annotations


def render_rules(acceptance_cmd: str | None = None) -> str:
    """Generate the standard rules of engagement for external coding harnesses."""
    lines = [
        "## RULES OF ENGAGEMENT",
        "1. Work strictly inside the current working directory (the git worktree).",
        "2. Never touch, read, or modify files outside the repository root.",
        "3. Commit all your changes on the current git branch with a clear commit message.",
        "4. Never run 'git push' or touch any remote repositories.",
        "5. Do not use browser, web search, image generation, or scheduling tools unless the brief explicitly requests them.",
    ]
    if acceptance_cmd:
        lines.append(f"6. Acceptance test command: `{acceptance_cmd}`. Run this command to verify your work before completing.")
    else:
        lines.append("6. Run existing project tests or linters if available to verify your changes.")
    lines.append("7. Finish with a concise summary of what changed and what remains to be done.")
    return "\n".join(lines)


def render_brief(task: str, files: list[str] | None = None) -> str:
    """Render the user task brief, adding file hints if provided."""
    parts = [task.strip()]
    if files:
        parts.append("\nRelevant files to look at:")
        for f in files:
            parts.append(f"- {f.strip()}")
    return "\n".join(parts)


def render_acceptance_failure_prompt(acceptance_cmd: str, output: str, max_tail: int = 4000) -> str:
    """Format a follow-up prompt when acceptance verification fails."""
    tail = output[-max_tail:] if len(output) > max_tail else output
    return (
        f"The acceptance command `{acceptance_cmd}` failed with the following output:\n\n"
        f"```\n{tail}\n```\n\n"
        "Please fix the issues, re-run the acceptance command, and commit your changes."
    )

"""Slash command handler for /code commands."""

from __future__ import annotations

import time
from pathlib import Path
from typing import TYPE_CHECKING

from nanobot.bus.events import OutboundMessage
from nanobot.coworker.coding.brief import render_rules
from nanobot.coworker.coding.runner import CodingRunner
from nanobot.coworker.config import load_coworker_config
from nanobot.coworker.runtime import services, spawn_background

if TYPE_CHECKING:
    from nanobot.command.router import CommandContext


def _reply(ctx: CommandContext, text: str) -> OutboundMessage:
    return OutboundMessage(
        channel=ctx.msg.channel,
        chat_id=ctx.msg.chat_id,
        content=text,
        metadata={**dict(ctx.msg.metadata or {}), "render_as": "text"},
    )


def _get_runner() -> CodingRunner:
    svc = services()
    ws_root = svc.workspace if svc is not None else Path.cwd()
    cfg = load_coworker_config()
    return CodingRunner(cfg, ws_root)


async def cmd_code(ctx: CommandContext) -> OutboundMessage:
    args = ctx.args.strip()
    parts = args.split(maxsplit=2)
    subcmd = parts[0].lower() if parts else "list"

    runner = _get_runner()

    if subcmd == "list":
        tasks = runner.registry.list_tasks()
        if not tasks:
            return _reply(ctx, "No coding tasks found.")
        lines = ["📋 **Coding Tasks**:"]
        now = time.time()
        for t in tasks[:15]:
            elapsed_m = int((now - t.created_at) / 60)
            lines.append(f"- `{t.id}` [{t.backend}] — **{t.status}** ({elapsed_m}m ago): {t.brief[:50]}")
        return _reply(ctx, "\n".join(lines))

    if subcmd == "status":
        if len(parts) < 2:
            return _reply(ctx, "Usage: /code status <task-id>")
        task_id = parts[1]
        t = runner.registry.get(task_id)
        if not t:
            return _reply(ctx, f"Task '{task_id}' not found.")
        lines = [
            f"**Task**: `{t.id}` ({t.backend})",
            f"**Status**: `{t.status}`",
            f"**Goal**: {t.brief}",
            f"**Repo**: `{t.repo}` (base: `{t.base}`, branch: `{t.branch}`)",
            f"**Commits**: {len(t.commits)} commit(s)",
        ]
        if t.error:
            lines.append(f"**Error**: {t.error}")
        if t.diffstat:
            lines.extend(["**Diffstat**:", "```", t.diffstat, "```"])
        return _reply(ctx, "\n".join(lines))

    if subcmd == "diff":
        if len(parts) < 2:
            return _reply(ctx, "Usage: /code diff <task-id>")
        task_id = parts[1]
        t = runner.registry.get(task_id)
        if not t:
            return _reply(ctx, f"Task '{task_id}' not found.")
        worktree_path = Path(t.worktree)
        if not worktree_path.exists():
            return _reply(ctx, f"Worktree for task '{task_id}' is no longer available.")
        diff_text = await runner.workspace_mgr.get_full_diff(worktree_path, t.base)
        if not diff_text.strip():
            return _reply(ctx, f"No diff found for task '{task_id}'.")
        if len(diff_text) > 4000:
            diff_text = diff_text[:4000] + "\n... [diff truncated]"
        return _reply(ctx, f"```diff\n{diff_text}\n```")

    if subcmd == "steer":
        if len(parts) < 3:
            return _reply(ctx, "Usage: /code steer <task-id> <message>")
        task_id = parts[1]
        message = parts[2]
        try:
            await runner.steer(task_id, message)
            return _reply(ctx, f"Steering message sent to task `{task_id}`.")
        except Exception as e:
            return _reply(ctx, f"Error steering task `{task_id}`: {e}")

    if subcmd == "abort":
        if len(parts) < 2:
            return _reply(ctx, "Usage: /code abort <task-id>")
        task_id = parts[1]
        try:
            await runner.abort(task_id)
            return _reply(ctx, f"Task `{task_id}` aborted.")
        except Exception as e:
            return _reply(ctx, f"Error aborting task `{task_id}`: {e}")

    if subcmd == "merge":
        if len(parts) < 2:
            return _reply(ctx, "Usage: /code merge <task-id>")
        task_id = parts[1]
        t = runner.registry.get(task_id)
        if not t:
            return _reply(ctx, f"Task '{task_id}' not found.")
        try:
            repo_cfg = runner.workspace_mgr.validate_repo(t.repo)
            commit_msg = (
                f"{t.brief}\n\nTask: {t.id}\nBackend: {t.backend}\n\n"
                f"{t.summary or 'Merged coding agent work'}"
            )
            ok, msg = await runner.workspace_mgr.merge(
                repo=repo_cfg,
                task_id=t.id,
                base_ref=t.base,
                strategy=runner.config.coding.merge_strategy,
                commit_message=commit_msg,
            )
            if ok:
                return _reply(
                    ctx,
                    f"✅ Successfully merged `{task_id}` into `{t.base}`.\n"
                    "Note: If merging into the gateway repo checkout, changes take effect after restart.",
                )
            return _reply(ctx, f"❌ Merge refused: {msg}")
        except Exception as e:
            return _reply(ctx, f"❌ Merge failed with error: {e}")

    if subcmd == "discard":
        if len(parts) < 2:
            return _reply(ctx, "Usage: /code discard <task-id>")
        task_id = parts[1]
        t = runner.registry.get(task_id)
        if not t:
            return _reply(ctx, f"Task '{task_id}' not found.")
        try:
            repo_cfg = runner.workspace_mgr.validate_repo(t.repo)
            await runner.workspace_mgr.cleanup(repo=repo_cfg, task_id=t.id, delete_branch=True)
            t.status = "aborted"
            runner.registry.save(t)
            return _reply(ctx, f"🗑️ Discarded task `{task_id}` worktree and branch.")
        except Exception as e:
            return _reply(ctx, f"Error discarding task `{task_id}`: {e}")

    if subcmd == "resume":
        if len(parts) < 3:
            return _reply(ctx, "Usage: /code resume <task-id> <message>")
        task_id = parts[1]
        follow_up_msg = parts[2]
        t = runner.registry.get(task_id)
        if not t:
            return _reply(ctx, f"Task '{task_id}' not found.")
        if not t.resume_ref:
            return _reply(ctx, f"Task '{task_id}' has no saved session or conversation reference to resume.")

        try:
            repo_cfg = runner.workspace_mgr.validate_repo(t.repo)
            from nanobot.coworker.coding.backends.base import backend_for

            backend = backend_for(t.backend, runner.config)
            worktree_path = Path(t.worktree)
            if not worktree_path.exists():
                return _reply(ctx, f"Worktree '{t.worktree}' not found.")

            rules = render_rules(t.acceptance)

            async def _resume_run() -> None:
                run = backend.follow_up(
                    run_ref=t.resume_ref,  # type: ignore[arg-type]
                    message=follow_up_msg,
                    cwd=worktree_path,
                    rules=rules,
                    task_id=t.id,
                )
                async for _ in run:
                    pass
                t.status = "succeeded"
                runner.registry.save(t)

            spawn_background(_resume_run(), name=f"resume-{task_id}")
            return _reply(ctx, f"▶️ Resuming task `{task_id}` with follow-up message.")
        except Exception as e:
            return _reply(ctx, f"Error resuming task `{task_id}`: {e}")

    return _reply(
        ctx,
        "Usage: /code list | status <id> | diff <id> | steer <id> <msg> | abort <id> | merge <id> | discard <id> | resume <id> <msg>",
    )

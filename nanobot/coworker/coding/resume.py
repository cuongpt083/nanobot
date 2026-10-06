"""Notify chats about coding tasks that a gateway restart left interrupted."""

from __future__ import annotations

from pathlib import Path

from loguru import logger

from nanobot.coworker.coding.tasks import shared_registry
from nanobot.coworker.runtime import post_to_chat


async def notify_interrupted_tasks(workspace_root: Path) -> None:
    """Tell each affected chat that its coding task can be resumed."""
    try:
        registry = shared_registry(workspace_root)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning(f"could not load coding registry for interruption notice: {exc}")
        return
    for task in registry.interrupted_at_boot():
        content = (
            f"⚠️ Coding task `{task.id}` was interrupted by a restart "
            f"(phase `{task.phase}`, status `{task.status}`). "
            f"Run `/code resume {task.id}` to continue, or `/code discard {task.id}` to drop it."
        )
        try:
            await post_to_chat(channel=task.channel, chat_id=task.chat_id, content=content)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning(f"failed to notify interrupted coding task {task.id}: {exc}")

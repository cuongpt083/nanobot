"""Resolve which directory a coding task works on, and whether the model may choose it.

Trust boundary: the project directory the user picked in the WebUI (persisted in the session's
``workspace_scope``) and the ``coding.repos`` allowlist are the only sources. A path supplied by
the model (``repo`` argument) is accepted only when it names one of those, so the model can never
widen the set of directories a harness may run in.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, cast

from nanobot.coworker.config import RepoConfig
from nanobot.coworker.runtime import session_state
from nanobot.security.workspace_access import (
    WORKSPACE_SCOPE_METADATA_KEY,
    WorkspaceScopeError,
    validate_workspace_scope_payload,
)

if TYPE_CHECKING:
    from nanobot.coworker.config import CodingAgentConfig


class ProjectError(RuntimeError):
    """The coding project could not be resolved or is not allowed."""


class DirectConfirmationError(ProjectError):
    """The project is not a git repository and the user has not agreed to in-place edits yet."""

    def __init__(self, path: Path, message: str) -> None:
        super().__init__(message)
        self.path = path


@dataclass(frozen=True)
class ProjectTarget:
    """Directory a coding task runs against, plus optional per-project defaults."""

    path: Path
    profile: RepoConfig | None
    source: Literal["scope", "config"]

    @property
    def repo_config(self) -> RepoConfig:
        """Profile when one matches the path, otherwise defaults (HEAD, global backend)."""
        return self.profile if self.profile is not None else RepoConfig(path=str(self.path))


def path_key(path: str | Path) -> str:
    """Comparable form of a path (resolved, case-folded on Windows)."""
    return os.path.normcase(str(Path(path).expanduser().resolve()))


def _find_profile(cfg: CodingAgentConfig, path: str | Path) -> RepoConfig | None:
    key = path_key(path)
    for repo in cfg.repos:
        if path_key(repo.path) == key:
            return repo
    return None


def direct_allowed(session: Any | None, path: str | Path) -> bool:
    """Has the user agreed (in this chat) to the coding agent editing ``path`` in place?"""
    if session is None:
        return False
    coding = session_state(session).get("coding")
    if not isinstance(coding, dict):
        return False
    allowed = cast("dict[str, Any]", coding).get("direct_ok")
    return isinstance(allowed, list) and path_key(path) in cast("list[Any]", allowed)


def grant_direct(session: Any, path: str | Path) -> None:
    """Record the user's consent for ``path`` (set by the UI / ``/code direct allow``, never the model)."""
    state = session_state(session)
    coding = state.get("coding")
    if not isinstance(coding, dict):
        coding = {}
        state["coding"] = coding
    coding = cast("dict[str, Any]", coding)
    allowed: list[str] = []
    existing = coding.get("direct_ok")
    if isinstance(existing, list):
        allowed = [str(item) for item in cast("list[Any]", existing)]
    key = path_key(path)
    if key not in allowed:
        allowed.append(key)
    coding["direct_ok"] = allowed
    clear_pending_direct(session, path)


def revoke_direct(session: Any, path: str | Path) -> None:
    """Withdraw consent for ``path`` and forget a pending request for it."""
    coding = session_state(session).get("coding")
    if not isinstance(coding, dict):
        return
    coding = cast("dict[str, Any]", coding)
    existing = coding.get("direct_ok")
    key = path_key(path)
    if isinstance(existing, list):
        coding["direct_ok"] = [item for item in cast("list[Any]", existing) if item != key]
    clear_pending_direct(session, path)


def set_pending_direct(session: Any, path: str | Path) -> None:
    """Remember that a coding task wanted to edit ``path`` in place, so the UI can ask the user."""
    state = session_state(session)
    coding = state.get("coding")
    if not isinstance(coding, dict):
        coding = {}
        state["coding"] = coding
    cast("dict[str, Any]", coding)["pending_direct"] = str(Path(path).expanduser().resolve())


def pending_direct(session: Any | None) -> str | None:
    if session is None:
        return None
    coding = session_state(session).get("coding")
    if not isinstance(coding, dict):
        return None
    value = cast("dict[str, Any]", coding).get("pending_direct")
    return value if isinstance(value, str) and value else None


def clear_pending_direct(session: Any, path: str | Path | None = None) -> None:
    coding = session_state(session).get("coding")
    if not isinstance(coding, dict):
        return
    coding = cast("dict[str, Any]", coding)
    current = coding.get("pending_direct")
    if current is None:
        return
    if path is None or path_key(str(current)) == path_key(path):
        coding.pop("pending_direct", None)


def session_project_path(session: Any | None) -> Path | None:
    """Directory the user explicitly picked for this session, or None.

    Only an explicit ``workspace_scope`` counts: a session without one runs in the default
    workspace, which must not silently become a coding repository.
    """
    metadata = getattr(session, "metadata", None) if session is not None else None
    if not isinstance(metadata, dict):
        return None
    meta = cast("dict[str, Any]", metadata)
    if WORKSPACE_SCOPE_METADATA_KEY not in meta:
        return None
    raw = meta[WORKSPACE_SCOPE_METADATA_KEY]
    try:
        scope = validate_workspace_scope_payload(
            raw, default_workspace=Path.cwd(), default_restrict_to_workspace=False
        )
    except WorkspaceScopeError as exc:
        raise ProjectError(
            f"The project directory chosen for this chat is no longer usable: {exc.message}. "
            "Pick the project directory again."
        ) from exc
    return scope.project_path


def resolve_project(
    session: Any | None,
    cfg: CodingAgentConfig,
    repo_arg: str | None = None,
) -> ProjectTarget:
    """Pick the project for a coding task.

    Order: the session's chosen project directory, then the only configured repo. ``repo_arg``
    (model-controlled) must equal the chosen directory or be one of ``cfg.repos``.
    """
    scope_path = session_project_path(session)

    if repo_arg:
        if scope_path is not None and path_key(repo_arg) == path_key(scope_path):
            return ProjectTarget(scope_path, _find_profile(cfg, scope_path), "scope")
        profile = _find_profile(cfg, repo_arg)
        if profile is None:
            allowed = [str(scope_path)] if scope_path is not None else []
            allowed += [r.path for r in cfg.repos]
            raise ProjectError(
                f"Repository '{repo_arg}' is not allowed. Allowed: {allowed or 'none'}. "
                "The project directory is chosen by the user, not by the agent."
            )
        return ProjectTarget(Path(profile.path).expanduser().resolve(), profile, "config")

    if scope_path is not None:
        return ProjectTarget(scope_path, _find_profile(cfg, scope_path), "scope")

    if not cfg.repos:
        raise ProjectError(
            "No repositories configured in coding.repos and no project directory is selected "
            "for this chat; execution is refused. Choose a project directory in the WebUI."
        )
    if len(cfg.repos) == 1:
        only = cfg.repos[0]
        return ProjectTarget(Path(only.path).expanduser().resolve(), only, "config")
    raise ValueError(f"Ambiguous repository; specify one of: {[r.path for r in cfg.repos]}")

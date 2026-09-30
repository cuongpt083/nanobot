"""Coworker extension configuration.

Lives in its own file (default ``~/.nanobot/coworker.json``, override with
``NANOBOT_COWORKER_CONFIG``) so the fork never edits the upstream config schema.
The file is re-read when its mtime changes, so edits apply without a restart.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Literal

from loguru import logger
from pydantic import Field, ValidationError, field_validator

from nanobot.config_base import Base

_AGENT_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


class AdvisorConfig(Base):
    """Stronger-model reviewer consulted by the ``advisor`` tool."""

    preset: str | None = None  # model preset name from config.json; None = disabled
    max_uses: int = Field(default=10, ge=1, le=200)
    max_tokens: int = Field(default=4096, ge=256, le=64000)
    timeout_seconds: int = Field(default=180, ge=10, le=1800)
    review_nudge: bool = True
    first_consult_gap: int = Field(default=2, ge=1)
    reconsult_gap: int = Field(default=12, ge=3)


class RoomAgentConfig(Base):
    """A named teammate that can take turns in a multi-agent room."""

    id: str
    name: str = ""
    emoji: str = ""
    bio: str = ""
    preset: str | None = None  # model preset; None = the owner's runtime
    backend: Literal["pi", "agy"] | None = None  # coding harness backend if used as coder
    instructions: str = ""

    @field_validator("id")
    @classmethod
    def _valid_id(cls, value: str) -> str:
        value = value.strip().lower()
        if not _AGENT_ID.fullmatch(value):
            raise ValueError("agent id must match [a-z0-9][a-z0-9_-]{0,63}")
        return value


class RoomConfig(Base):
    agents: list[RoomAgentConfig] = Field(default_factory=list)
    max_chained_turns: int = Field(default=16, ge=1, le=100)
    guest_timeout_seconds: int = Field(default=900, ge=30)


class TrimConfig(Base):
    enabled: bool = False
    max_turns: int = Field(default=20, ge=2, le=1000)


class KeepaliveConfig(Base):
    enabled: bool = False
    window_minutes: int = Field(default=30, ge=1, le=240)
    max_pings: int = Field(default=4, ge=1, le=20)
    lead_seconds: int = Field(default=60, ge=5, le=600)


class ContextConfig(Base):
    trim: TrimConfig = Field(default_factory=TrimConfig)
    optimize: bool = False
    freeze_system_prompt: bool = False
    freeze_max_hold_minutes: int = Field(default=60, ge=1)
    cache_ttl_seconds: int | None = Field(default=None, ge=30)
    keepalive: KeepaliveConfig = Field(default_factory=KeepaliveConfig)


class WorkflowConfig(Base):
    enabled: bool = True
    step_max_retries: int = Field(default=3, ge=1, le=10)
    max_step_turns: int = Field(default=100, ge=1)


class PiBackendConfig(Base):
    command: list[str] = ["pi"]
    agent_dir: str | None = None
    tools: list[str] | None = None
    extensions: bool = True
    trust_project_files: bool = False
    pass_env: list[str] = Field(default_factory=list)
    allow_unsandboxed: bool = False


_AGY_DISALLOWED_FLAGS = {
    "--model",
    "-model",
    "--effort",
    "-effort",
    "-p",
    "--print",
    "-print",
    "--prompt",
    "-prompt",
    "--output-format",
    "-output-format",
    "--conversation",
    "-conversation",
    "-c",
    "--continue",
    "-continue",
}


class AgyBackendConfig(Base):
    command: list[str] = ["agy"]
    agy_sandbox: bool = True
    mode: Literal["accept-edits"] | None = None
    extra_args: list[str] = Field(default_factory=list)
    pass_env: list[str] = Field(default_factory=list)
    allow_unsandboxed: bool = False

    @field_validator("extra_args")
    @classmethod
    def _validate_extra_args(cls, args: list[str]) -> list[str]:
        for arg in args:
            flag = arg.split("=", 1)[0].strip()
            if flag in _AGY_DISALLOWED_FLAGS:
                raise ValueError(f"disallowed flag in extra_args: {flag}")
        return args


class RepoConfig(Base):
    path: str
    acceptance: str | None = None
    base_ref: str = "HEAD"
    backend: Literal["pi", "agy"] | None = None


class CodingAgentConfig(Base):
    enabled: bool = False
    default_backend: Literal["pi", "agy"] = "pi"
    pi: PiBackendConfig = Field(default_factory=PiBackendConfig)
    agy: AgyBackendConfig = Field(default_factory=AgyBackendConfig)
    repos: list[RepoConfig] = Field(default_factory=list)
    worktree_root: str | None = None
    sandbox: Literal["none", "bwrap"] = "none"
    timeout_minutes: int = Field(default=45, ge=1)
    idle_timeout_minutes: int = Field(default=10, ge=1)
    max_concurrent_per_session: int = Field(default=1, ge=1)
    max_concurrent_total: int = Field(default=2, ge=1)
    fix_rounds: int = Field(default=1, ge=0)
    progress_every_seconds: int = Field(default=60, ge=1)
    merge_strategy: Literal["squash", "no-ff", "ff-only"] = "squash"
    delete_branch_after_merge: bool = True
    keep_failed_worktrees_days: int = Field(default=3, ge=0)


class CoworkerConfig(Base):
    advisor: AdvisorConfig = Field(default_factory=AdvisorConfig)
    room: RoomConfig = Field(default_factory=RoomConfig)
    context: ContextConfig = Field(default_factory=ContextConfig)
    workflows: WorkflowConfig = Field(default_factory=WorkflowConfig)
    coding: CodingAgentConfig = Field(default_factory=CodingAgentConfig)

    def agent(self, agent_id: str) -> RoomAgentConfig | None:
        key = agent_id.strip().lstrip("@").lower()
        return next((a for a in self.room.agents if a.id == key), None)


def coworker_config_path() -> Path:
    override = os.environ.get("NANOBOT_COWORKER_CONFIG", "").strip()
    if override:
        return Path(override).expanduser()
    from nanobot.config.loader import get_config_path

    return get_config_path().expanduser().parent / "coworker.json"


_cache: tuple[Path, float, CoworkerConfig] | None = None
_override: CoworkerConfig | None = None


def load_coworker_config() -> CoworkerConfig:
    """Return the current config; a missing or invalid file yields defaults."""
    global _cache
    if _override is not None:
        return _override
    path = coworker_config_path()
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return CoworkerConfig()
    if _cache is not None and _cache[0] == path and _cache[1] == mtime:
        return _cache[2]
    try:
        config = CoworkerConfig.model_validate(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError, ValidationError) as exc:
        logger.warning("Ignoring invalid coworker config {}: {}", path, exc)
        config = CoworkerConfig()
    _cache = (path, mtime, config)
    return config


def invalidate_coworker_config_cache() -> None:
    """Force the next load to re-read the file (used right after the WebUI writes it)."""
    global _cache
    _cache = None


def set_coworker_config_override(config: CoworkerConfig | None) -> None:
    """Pin the config in-process (tests and SDK embedding)."""
    global _override
    _override = config

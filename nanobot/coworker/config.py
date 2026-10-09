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
from pydantic import Field, ValidationError, field_validator, model_validator

from nanobot.config_base import Base

_AGENT_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


class ExecutorProfile(Base):
    """Per-executor-model overrides of the advisor timing (weaker executors get tighter leashes)."""

    first_consult_gap: int | None = Field(default=None, ge=1)
    reconsult_gap: int | None = Field(default=None, ge=2)
    checkpoint_files: int | None = Field(default=None, ge=2)
    commit_gate: bool | None = None


class AdvisorConfig(Base):
    """Stronger-model reviewer consulted by the ``advisor`` tool."""

    preset: str | None = None  # model preset name from config.json; None = disabled
    max_uses: int = Field(default=10, ge=1, le=200)
    max_tokens: int = Field(default=4096, ge=256, le=64000)
    timeout_seconds: int = Field(default=180, ge=10, le=1800)
    review_nudge: bool = True
    # Ask the coordinator to consult once before posting a room's final report. Off by default: in the
    # Phase 0/B eval it roughly doubled tokens per run with no quality gain distinguishable from run noise.
    room_review_nudge: bool = False
    first_consult_gap: int = Field(default=2, ge=1)
    reconsult_gap: int = Field(default=12, ge=3)
    discussion_gate: Literal["off", "brainstorm", "always"] = "brainstorm"
    discussion_min_chars: int = Field(default=800, ge=100)
    stuck_detection: bool = True
    # Steering (docs/coworker/proposals/advisor-steering.md); each flag is an independent kill switch.
    evidence_pack: bool = True  # A1/A2: harness-collected git/diff/test evidence for consults
    ledger: bool = True  # B1-B4: structured advice ledger, done-gate, advisor checkpoints
    # Fixed advice template (goal, definition of done, how-to) and the matching ledger fields. Off by default
    # until measured (docs/coworker/plans/advisor-output-template.md).
    output_template: bool = False
    # Let unmet definition-of-done items hold the done-gate too (needs output_template).
    done_gate_done_when: bool = False
    mid_run_checkpoints: bool = True  # C1/C3: notes on tool results mid-run
    checkpoint_files: int = Field(default=5, ge=2)  # distinct files written since the last consult
    commit_gate: bool = True  # C2: block a first commit/push/reset/rm until reviewed
    refill_steps: int = Field(default=25, ge=0)  # D1: +1 consult per N work steps (0 = fixed budget)
    executor_profiles: dict[str, ExecutorProfile] = Field(default_factory=dict)  # D2: model glob -> overrides


class NamePolicy(Base):
    allow: list[str] = Field(default_factory=list)  # glob (fnmatch); empty = legacy default
    deny: list[str] = Field(default_factory=list)


class SkillPolicy(Base):
    inherit: list[str] = Field(default_factory=list)  # skills from <workspace>/skills or builtin
    deny: list[str] = Field(default_factory=list)


class RoomAgentConfig(Base):
    """A named teammate that can take turns in a multi-agent room."""

    id: str
    name: str = ""
    emoji: str = ""
    bio: str = ""
    preset: str | None = None  # model preset; None = the owner's runtime
    instructions: str = ""
    home: str | None = None  # relative to workspace, e.g. "agents/nutri-coach"
    tools: NamePolicy = Field(default_factory=NamePolicy)
    skills: SkillPolicy = Field(default_factory=SkillPolicy)
    memory: Literal["none", "thread", "thread+notes"] = "thread"
    thread_turns: int = Field(default=8, ge=0, le=50)
    max_iterations: int = Field(default=40, ge=1, le=500)
    output_contract: Literal["none", "default"] = "default"

    @model_validator(mode="before")
    @classmethod
    def _migrate_legacy_fields(cls, data: object) -> object:
        if isinstance(data, dict) and "backend" in data:
            data = dict(data)
            legacy_backend = data.pop("backend")
            if legacy_backend:
                logger.warning(
                    f"RoomAgentConfig: 'backend' field is deprecated and removed from room guests (got {legacy_backend!r}). "
                    "Room guests now run via AgentRuntime."
                )
        return data

    @field_validator("id")
    @classmethod
    def _valid_id(cls, value: str) -> str:
        value = value.strip().lower()
        if not _AGENT_ID.fullmatch(value):
            raise ValueError("agent id must match [a-z0-9][a-z0-9_-]{0,63}")
        return value

    @field_validator("home")
    @classmethod
    def _valid_home(cls, value: str | None) -> str | None:
        if value is None:
            return None
        clean = value.strip()
        if not clean:
            return None
        p = Path(clean)
        if p.is_absolute() or ".." in p.parts or clean.startswith(("\\", "/")):
            raise ValueError("home must be a relative path and cannot contain '..'")
        # Also disallow drive-anchor paths on Windows like C:foo
        if p.drive:
            raise ValueError("home must be a relative path without drive specifications")
        return p.as_posix()


class RoomConfig(Base):
    agents: list[RoomAgentConfig] = Field(default_factory=list)
    max_chained_turns: int = Field(default=16, ge=1, le=100)
    guest_timeout_seconds: int = Field(default=900, ge=30)
    max_parallel: int = Field(default=1, ge=1, le=8)
    context_turns: int = Field(default=5, ge=1, le=20)
    min_context_chars: int = Field(default=80, ge=0)
    legacy_guest_runner: bool = False


class TrimConfig(Base):
    enabled: bool = False
    max_turns: int = Field(default=20, ge=2, le=1000)


class KeepaliveConfig(Base):
    enabled: bool = False
    strategy: Literal["ping", "ttl1h"] = "ping"
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


class PiPhaseConfig(Base):
    model: str | None = None
    thinking: Literal["off", "minimal", "low", "medium", "high", "xhigh", "max"] | None = None


class PiPhases(Base):
    plan: PiPhaseConfig = Field(default_factory=lambda: PiPhaseConfig(thinking="high"))
    implement: PiPhaseConfig = Field(default_factory=lambda: PiPhaseConfig(thinking="medium"))
    review: PiPhaseConfig = Field(default_factory=lambda: PiPhaseConfig(thinking="high"))


class PiBackendConfig(Base):
    command: list[str] = ["pi"]
    min_version: str = "1.0.0"
    max_record_mb: int = Field(default=64, ge=1)
    tool_timeout_minutes: int = Field(default=20, ge=1)
    agent_dir: str | None = None
    tools: list[str] | None = None
    extensions: bool = True
    trust_project_files: bool = False
    pass_env: list[str] = Field(default_factory=list)
    allow_unsandboxed: bool = False
    phases: PiPhases = Field(default_factory=PiPhases)



class RepoConfig(Base):
    path: str
    acceptance: str | None = None
    base_ref: str = "HEAD"
    backend: Literal["pi"] | None = None

    @model_validator(mode="before")
    @classmethod
    def _migrate_repo_backend(cls, data: object) -> object:
        if isinstance(data, dict) and data.get("backend") == "agy":
            data = dict(data)
            logger.warning("RepoConfig: backend 'agy' is no longer supported; defaulting to 'pi'")
            data["backend"] = "pi"
        return data


class CodingAgentConfig(Base):
    enabled: bool = False
    default_backend: Literal["pi"] = "pi"
    pi: PiBackendConfig = Field(default_factory=PiBackendConfig)
    repos: list[RepoConfig] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _migrate_coding_config(cls, data: object) -> object:
        if isinstance(data, dict):
            data = dict(data)
            if data.get("default_backend") == "agy":
                logger.warning("CodingAgentConfig: default_backend 'agy' is no longer supported; using 'pi'")
                data["default_backend"] = "pi"
            if "agy" in data:
                data.pop("agy")
        return data
    worktree_root: str | None = None
    sandbox: Literal["none", "bwrap", "seatbelt", "wsl"] = "none"
    # wsl (Windows): distro that runs the harness under bwrap; None = the default distro. The
    # harness (pi) must be installed and logged in inside it.
    wsl_distro: str | None = None
    # bwrap / seatbelt / wsl: extra paths the harness may read / write (its own state dir and the
    # project are always mounted). E.g. a node install under $HOME that ``pi`` needs: ["~/.nvm"].
    # With ``wsl`` these are Linux paths inside the distro (``~`` is the distro's home).
    sandbox_ro_binds: list[str] = Field(default_factory=list)
    sandbox_rw_binds: list[str] = Field(default_factory=list)
    timeout_minutes: int = Field(default=45, ge=1)
    idle_timeout_minutes: int = Field(default=10, ge=1)
    max_concurrent_per_session: int = Field(default=1, ge=1)
    max_concurrent_total: int = Field(default=2, ge=1)
    fix_rounds: int = Field(default=1, ge=0)
    progress_every_seconds: int = Field(default=60, ge=1)
    merge_strategy: Literal["squash", "no-ff", "ff-only"] = "squash"
    delete_branch_after_merge: bool = True
    keep_failed_worktrees_days: int = Field(default=3, ge=0)
    # Projects without git (documents, slides…): ``ask`` needs the user's confirmation per chat and
    # directory, ``direct`` edits in place straight away, ``refuse`` never runs the harness there.
    non_git: Literal["ask", "direct", "refuse"] = "ask"
    snapshot_max_mb: int = Field(default=200, ge=1)
    # Extra directories (and everything below) a coding task may never run in, on top of the
    # built-in list (filesystem root, home, system and credential directories).
    blocked_paths: list[str] = Field(default_factory=list)
    # What to do when a task changed files outside its project (credentials, shell startup files,
    # git hooks, the user's own checkout): ``warn`` reports it, ``fail`` also marks the task failed.
    outside_writes: Literal["warn", "fail"] = "warn"

    plan_approval: Literal["always", "auto", "never"] = "auto"
    plan_auto_max_steps: int = Field(default=6, ge=1)
    min_context_chars: int = Field(default=120, ge=0)
    settle_max_continuations: int = Field(default=2, ge=0, le=5)
    ask_timeout_minutes: int = Field(default=10, ge=1)
    ask_user_timeout_minutes: int = Field(default=60, ge=1)
    wait_max_minutes: int = Field(default=10, ge=1, le=30)
    review: bool = True


class StagingConfig(Base):
    """Reviewed file changes (Phase 8). Off by default until the editor review path is verified."""

    enabled: bool = False


class CoworkerConfig(Base):
    advisor: AdvisorConfig = Field(default_factory=AdvisorConfig)
    room: RoomConfig = Field(default_factory=RoomConfig)
    context: ContextConfig = Field(default_factory=ContextConfig)
    workflows: WorkflowConfig = Field(default_factory=WorkflowConfig)
    coding: CodingAgentConfig = Field(default_factory=CodingAgentConfig)
    staging: StagingConfig = Field(default_factory=StagingConfig)

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

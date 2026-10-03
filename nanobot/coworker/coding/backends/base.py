"""Base protocol, events, and types for coding harnesses."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, Protocol, runtime_checkable

from nanobot.coworker.coding.sandbox import SandboxPolicy

if TYPE_CHECKING:
    from nanobot.coworker.config import CoworkerConfig


@dataclass(frozen=True)
class BackendStats:
    input_tokens: int = 0
    output_tokens: int = 0
    thinking_tokens: int = 0
    cache_read_tokens: int = 0
    total_tokens: int = 0
    cost: float = 0.0

    def diff_from_previous(self, prev: BackendStats) -> BackendStats:
        """Calculate incremental stats given cumulative totals."""
        return BackendStats(
            input_tokens=max(0, self.input_tokens - prev.input_tokens),
            output_tokens=max(0, self.output_tokens - prev.output_tokens),
            thinking_tokens=max(0, self.thinking_tokens - prev.thinking_tokens),
            cache_read_tokens=max(0, self.cache_read_tokens - prev.cache_read_tokens),
            total_tokens=max(0, self.total_tokens - prev.total_tokens),
            cost=max(0.0, self.cost - prev.cost),
        )

    def add(self, other: BackendStats) -> BackendStats:
        return BackendStats(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            thinking_tokens=self.thinking_tokens + other.thinking_tokens,
            cache_read_tokens=self.cache_read_tokens + other.cache_read_tokens,
            total_tokens=self.total_tokens + other.total_tokens,
            cost=self.cost + other.cost,
        )


@dataclass(frozen=True)
class BackendResult:
    status: Literal["succeeded", "failed_acceptance", "aborted", "timed_out", "error"]
    response: str = ""
    summary: str = ""
    stats: BackendStats = field(default_factory=BackendStats)
    error: str | None = None
    raw_error_line: str | None = None


@dataclass(frozen=True)
class BackendEventProgress:
    message: str
    tool_count: int = 0
    last_tool: str | None = None


@dataclass(frozen=True)
class BackendEventTool:
    tool_name: str
    tool_call_id: str | None = None
    parameters: dict[str, Any] = field(default_factory=dict)
    state: Literal["start", "update", "end"] = "start"


@dataclass(frozen=True)
class BackendEventText:
    text: str


@dataclass(frozen=True)
class BackendEventDone:
    result: BackendResult
    resume_ref: str | None = None


@dataclass(frozen=True)
class BackendEventError:
    error: str
    raw_line: str | None = None


BackendEvent = (
    BackendEventProgress
    | BackendEventTool
    | BackendEventText
    | BackendEventDone
    | BackendEventError
)


@dataclass(frozen=True)
class BackendCapabilities:
    steer: bool = False
    live_stats: bool = False


@runtime_checkable
class BackendRun(Protocol):
    """An active harness execution yielding backend events."""

    def __aiter__(self) -> AsyncIterator[BackendEvent]: ...


@runtime_checkable
class CodingBackend(Protocol):
    """Protocol satisfied by Pi and agy coding harness adapters."""

    @property
    def name(self) -> str: ...

    @property
    def capabilities(self) -> BackendCapabilities: ...

    def start(
        self,
        *,
        brief: str,
        cwd: Path,
        rules: str,
        task_id: str,
        session_dir: Path | None = None,
    ) -> BackendRun: ...

    def follow_up(
        self,
        *,
        run_ref: str,
        message: str,
        cwd: Path,
        rules: str,
        task_id: str,
        session_dir: Path | None = None,
    ) -> BackendRun: ...

    async def steer(self, message: str) -> None: ...

    async def abort(self) -> None: ...

    async def stats(self) -> BackendStats: ...


def _sandbox_policy(config: CoworkerConfig) -> SandboxPolicy:
    coding = config.coding
    # With WSL the paths are Linux paths in the distro: ``~`` must not become the Windows home.
    def prep(path: str) -> str:
        return path if coding.sandbox == "wsl" else str(Path(path).expanduser())

    return SandboxPolicy(
        mode=coding.sandbox,
        ro_binds=tuple(prep(p) for p in coding.sandbox_ro_binds),
        rw_binds=tuple(prep(p) for p in coding.sandbox_rw_binds),
        distro=coding.wsl_distro,
    )


def backend_for(name: str, config: CoworkerConfig) -> CodingBackend:
    """Instantiate a coding backend by name."""
    clean = name.strip().lower()
    if clean == "pi":
        from nanobot.coworker.coding.backends.pi import PiBackend

        return PiBackend(
            config=config.coding.pi,
            global_sandbox=config.coding.sandbox,
            sandbox_policy=_sandbox_policy(config),
        )
    if clean == "agy":
        from nanobot.coworker.coding.backends.agy import AgyBackend

        return AgyBackend(
            config=config.coding.agy,
            global_sandbox=config.coding.sandbox,
            sandbox_policy=_sandbox_policy(config),
        )
    raise ValueError(f"Unknown coding backend: {name!r}. Supported: 'pi', 'agy'.")

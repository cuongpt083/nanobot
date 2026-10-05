"""Interface definition for coding runtimes."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from nanobot.coworker.coding.backends.base import BackendStats


@dataclass
class SessionSpec:
    session_file: Path | None = None
    session_dir: Path | None = None
    task_id: str = ""


@dataclass
class ModelSpec:
    provider: str | None = None
    model: str | None = None
    thinking: str | None = None


@dataclass
class RunOutcome:
    status: Literal["succeeded", "error", "timed_out", "aborted", "queued", "handled"]
    response: str = ""
    summary: str = ""
    stats: BackendStats = field(default_factory=BackendStats)
    error: str | None = None
    raw_error_line: str | None = None


class CodingRuntime(ABC):
    """Abstract interface for modern coding runtime harnesses (Pi, Pi Durable, etc.)."""

    @abstractmethod
    async def start(
        self,
        *,
        cwd: Path,
        session: SessionSpec,
        extension: Path | None = None,
        contract_file: Path | None = None,
        model: ModelSpec | None = None,
    ) -> None:
        """Start the runtime child process and initialize session."""
        ...

    @abstractmethod
    async def run_prompt(self, message: str) -> RunOutcome:
        """Execute a prompt turn and await settlement or disposition."""
        ...

    @abstractmethod
    async def steer(self, message: str) -> None:
        """Send steer guidance to active turn."""
        ...

    @abstractmethod
    async def follow_up(self, message: str) -> RunOutcome:
        """Send a follow up prompt within the same or resumed session."""
        ...

    @abstractmethod
    async def abort(self) -> None:
        """Abort active execution immediately."""
        ...

    @abstractmethod
    async def close(self) -> None:
        """Gracefully shutdown runtime process."""
        ...

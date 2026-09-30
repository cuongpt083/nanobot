"""Shared fixtures for coworker extension tests."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

import nanobot.agent.loop  # noqa: F401  # resolve config forward refs before session.manager
from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.coworker import runtime
from nanobot.coworker.advisor.consult import reset_breaker
from nanobot.coworker.config import CoworkerConfig, set_coworker_config_override
from nanobot.coworker.context import keepalive, optimizer
from nanobot.coworker.room import scheduler
from nanobot.session.manager import SessionManager


@dataclass
class FakeBus:
    inbound: list[InboundMessage] = field(default_factory=list)
    outbound: list[OutboundMessage] = field(default_factory=list)

    async def publish_inbound(self, msg: InboundMessage) -> None:
        self.inbound.append(msg)

    async def publish_outbound(self, msg: OutboundMessage) -> None:
        self.outbound.append(msg)


@dataclass
class Env:
    workspace: Path
    bus: FakeBus
    sessions: SessionManager
    subagents: Any = None

    def configure(self, config: CoworkerConfig) -> None:
        set_coworker_config_override(config)

    def bind(self) -> None:
        runtime.set_services(runtime.CoworkerServices(
            workspace=self.workspace,
            bus=self.bus,  # type: ignore[arg-type]
            sessions=self.sessions,
            subagents=self.subagents,
            provider_snapshot_loader=None,
        ))


@pytest.fixture(autouse=True)
def _isolated_coworker_state() -> Iterator[None]:
    reset_breaker()
    optimizer.reset_states()
    scheduler.reset_rooms()
    yield
    set_coworker_config_override(None)


@pytest.fixture
def env(tmp_path: Path) -> Iterator[Env]:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    environment = Env(workspace=workspace, bus=FakeBus(), sessions=SessionManager(workspace))
    set_coworker_config_override(CoworkerConfig())
    environment.bind()
    yield environment
    set_coworker_config_override(None)
    runtime.set_services(None)
    optimizer.reset_states()
    keepalive.cancel_all()
    scheduler.reset_rooms()
    reset_breaker()

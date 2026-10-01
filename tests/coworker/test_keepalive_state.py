"""Tests for keepalive_state: per-session inheritance, overrides, and window clamping."""

from __future__ import annotations

from types import SimpleNamespace

from nanobot.coworker.config import (
    ContextConfig,
    CoworkerConfig,
    KeepaliveConfig,
    set_coworker_config_override,
)
from nanobot.coworker.context import keepalive_state


def _session() -> SimpleNamespace:
    return SimpleNamespace(metadata={})


def test_keepalive_inherits_global_default() -> None:
    set_coworker_config_override(
        CoworkerConfig(
            context=ContextConfig(
                keepalive=KeepaliveConfig(
                    enabled=False,
                    strategy="ping",
                    window_minutes=30,
                )
            )
        )
    )
    try:
        session = _session()
        eff = keepalive_state.effective(session)
        assert eff.enabled is False
        assert eff.strategy == "ping"
        assert eff.window_min == 30
        assert eff.source == "global"
        assert eff.set_at == 0.0
    finally:
        set_coworker_config_override(None)


def test_keepalive_session_override_and_clear() -> None:
    set_coworker_config_override(
        CoworkerConfig(
            context=ContextConfig(
                keepalive=KeepaliveConfig(
                    enabled=False,
                    strategy="ping",
                    window_minutes=30,
                )
            )
        )
    )
    try:
        session = _session()
        # Enable on session
        eff = keepalive_state.apply(
            session,
            enabled=True,
            strategy="ttl1h",
            window_min=60,
            now=12345.0,
        )
        assert eff.enabled is True
        assert eff.strategy == "ttl1h"
        assert eff.window_min == 60
        assert eff.source == "session"
        assert eff.set_at == 12345.0

        # Re-fetch from session
        eff2 = keepalive_state.effective(session)
        assert eff2 == eff

        # Clear override (enabled=None)
        eff3 = keepalive_state.apply(session, enabled=None)
        assert eff3.enabled is False
        assert eff3.strategy == "ping"
        assert eff3.window_min == 30
        assert eff3.source == "global"
    finally:
        set_coworker_config_override(None)


def test_clamp_window() -> None:
    assert keepalive_state.clamp_window(None) == 30
    assert keepalive_state.clamp_window(0) == 1
    assert keepalive_state.clamp_window(-10) == 1
    assert keepalive_state.clamp_window(45) == 45
    assert keepalive_state.clamp_window(200) == 120

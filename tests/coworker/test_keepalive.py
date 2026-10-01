"""Tests for coworker keepalive module: evaluate logic, status_for, and restart recovery."""

from __future__ import annotations

import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from nanobot.coworker.context import cache_policy, keepalive
from nanobot.coworker.context.cache_policy import CacheTtlPolicy
from nanobot.coworker.context.keepalive import _Capture, evaluate, status_for
from nanobot.coworker.context.keepalive_state import KeepWarmSetting
from nanobot.coworker.runtime import session_state
from nanobot.providers.base import LLMResponse, LLMUsage


def _make_cap(
    *,
    real_at: float = 1000.0,
    last_touch: float = 1000.0,
    pings: int = 0,
    failures: int = 0,
    last_failure_at: float = 0.0,
    pinging: bool = False,
    in_flight: bool = False,
    provider: object | None = None,
) -> _Capture:
    if provider is None:
        provider = SimpleNamespace(provider_name="anthropic", backend="anthropic")
    return _Capture(
        session_id="s1",
        session_key="s1",
        provider=provider,
        model="claude-3-5-sonnet",
        messages=[{"role": "user", "content": "hi"}],
        tools=None,
        max_tokens=4096,
        temperature=0.7,
        reasoning_effort=None,
        real_at=real_at,
        last_touch=last_touch,
        pings=pings,
        failures=failures,
        last_failure_at=last_failure_at,
        pinging=pinging,
        in_flight=in_flight,
    )


def test_evaluate_kickstart() -> None:
    cap = _make_cap(last_touch=1000.0)
    setting = KeepWarmSetting(enabled=True, strategy="ping", window_min=30, set_at=1010.0, source="session")
    policy = CacheTtlPolicy(ttl_s=300.0, lead_s=60.0, ping_cap=6, guaranteed=True)

    action = evaluate(cap, setting, policy, now=1020.0)
    assert action == "kickstart"


def test_evaluate_ping_due() -> None:
    # TTL 300, lead 60 -> expires at 1300, due at 1240
    cap = _make_cap(last_touch=1000.0)
    setting = KeepWarmSetting(enabled=True, strategy="ping", window_min=30, set_at=900.0, source="session")
    policy = CacheTtlPolicy(ttl_s=300.0, lead_s=60.0, ping_cap=6, guaranteed=True)

    # Not due yet at 1200
    assert evaluate(cap, setting, policy, now=1200.0) == "none"

    # Due at 1240
    assert evaluate(cap, setting, policy, now=1240.0) == "ping"
    assert evaluate(cap, setting, policy, now=1250.0) == "ping"


def test_evaluate_rewarm_after_expired() -> None:
    # TTL 300 -> expires at 1300. now > 1320 -> rewarm
    cap = _make_cap(last_touch=1000.0)
    setting = KeepWarmSetting(enabled=True, strategy="ping", window_min=30, set_at=900.0, source="session")
    policy = CacheTtlPolicy(ttl_s=300.0, lead_s=60.0, ping_cap=6, guaranteed=True)

    assert evaluate(cap, setting, policy, now=1325.0) == "rewarm"


def test_evaluate_window_expired() -> None:
    # Window 30 min = 1800s. real_at = 1000. now = 2900 -> > 1800 past real_at
    cap = _make_cap(real_at=1000.0, last_touch=2700.0)
    setting = KeepWarmSetting(enabled=True, strategy="ping", window_min=30, set_at=900.0, source="session")
    policy = CacheTtlPolicy(ttl_s=300.0, lead_s=60.0, ping_cap=6, guaranteed=True)

    assert evaluate(cap, setting, policy, now=2900.0) == "none"


def test_evaluate_ping_cap_and_in_flight() -> None:
    cap = _make_cap(last_touch=1000.0, pings=6)
    setting = KeepWarmSetting(enabled=True, strategy="ping", window_min=30, set_at=900.0, source="session")
    policy = CacheTtlPolicy(ttl_s=300.0, lead_s=60.0, ping_cap=6, guaranteed=True)

    # Max pings reached
    assert evaluate(cap, setting, policy, now=1250.0) == "none"

    # In flight
    cap2 = _make_cap(last_touch=1000.0, pings=1, in_flight=True)
    assert evaluate(cap2, setting, policy, now=1250.0) == "none"


def test_evaluate_backoff_on_failures() -> None:
    # Failures >= 2, backoff for 120s
    cap = _make_cap(last_touch=1000.0, failures=2, last_failure_at=1200.0)
    setting = KeepWarmSetting(enabled=True, strategy="ping", window_min=30, set_at=900.0, source="session")
    policy = CacheTtlPolicy(ttl_s=300.0, lead_s=60.0, ping_cap=6, guaranteed=True)

    # Within 120s -> none
    assert evaluate(cap, setting, policy, now=1250.0) == "none"

    # After 120s (e.g. 1321s) -> allowed to ping or rewarm
    assert evaluate(cap, setting, policy, now=1330.0) == "rewarm"


def test_evaluate_ttl1h_anthropic_skips_periodic_ping() -> None:
    provider = SimpleNamespace(provider_name="anthropic", backend="anthropic")
    cap = _make_cap(last_touch=1000.0, provider=provider)
    setting = KeepWarmSetting(enabled=True, strategy="ttl1h", window_min=30, set_at=900.0, source="session")
    policy = CacheTtlPolicy(ttl_s=3600.0, lead_s=60.0, ping_cap=6, guaranteed=True)

    assert evaluate(cap, setting, policy, now=4500.0) == "none"


@pytest.mark.asyncio
async def test_send_ping_uses_session_context_and_updates_stats() -> None:
    provider = SimpleNamespace(provider_name="anthropic", backend="anthropic")
    provider.chat_with_context = AsyncMock(
        return_value=LLMResponse(
            content="ok",
            finish_reason="stop",
            usage=LLMUsage.reported(
                input_tokens=100,
                output_tokens=5,
                cache_read_tokens=80,
                cache_write_tokens=20,
            ),
        )
    )

    cap = _make_cap(provider=provider)
    await keepalive._send_ping(cap, kickstart=False)

    assert provider.chat_with_context.called
    kwargs = provider.chat_with_context.call_args.kwargs
    assert kwargs["provider_context"].session_id == "s1"

    assert cap.pings == 1
    assert cap.spent["pings"] == 1
    assert cap.spent["input"] == 100
    assert cap.spent["cache_read"] == 80
    assert cap.failures == 0


def test_status_for_with_capture() -> None:
    session = SimpleNamespace(key="s1", metadata={})
    runtime = SimpleNamespace(
        provider=SimpleNamespace(provider_name="anthropic", backend="anthropic"),
        model="claude-3-5-sonnet",
        generation=SimpleNamespace(max_tokens=4096, temperature=0.7, reasoning_effort=None),
    )
    keepalive.capture(
        "s1",
        runtime=runtime,
        messages=[{"role": "user", "content": "hello"}],
        tools=None,
        ttl_s=300.0,
        window_s=1800.0,
        max_pings=6,
        lead_s=60.0,
    )
    try:
        st = status_for(session)
        assert st["known"] is True
        assert st["provider"] == "anthropic"
        assert st["model"] == "claude-3-5-sonnet"
        assert st["guaranteed"] is True
        assert st["can_ping"] is False  # disabled globally by default
    finally:
        keepalive.cancel_all()


def test_status_for_restart_metadata() -> None:
    session = SimpleNamespace(key="s_restored", metadata={})
    state = session_state(session)
    state["cache"] = {
        "last_llm_call_at": 1000000.0,
        "provider": "anthropic",
        "model": "claude-3-5-sonnet",
    }
    st = status_for(session)
    assert st["known"] is True
    assert st["provider"] == "anthropic"
    assert st["model"] == "claude-3-5-sonnet"
    assert st["can_ping"] is False  # Cannot ping because no in-memory capture
    assert st["real_turn_at"] == 1000000.0

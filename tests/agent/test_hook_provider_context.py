"""Tests for hook-provided provider context adjustment."""

from __future__ import annotations

from dataclasses import replace

from nanobot.agent.hook import AgentHook, AgentHookContext, CompositeHook
from nanobot.providers.base import ProviderCallContext


class _StubHook(AgentHook):
    def __init__(self, retention: str | None = None, *, raises: bool = False) -> None:
        super().__init__()
        self._retention = retention
        self._raises = raises

    def adjust_provider_context(
        self,
        context: AgentHookContext,
        provider_context: ProviderCallContext,
    ) -> ProviderCallContext:
        if self._raises:
            raise RuntimeError("boom")
        if self._retention:
            return replace(provider_context, cache_retention=self._retention)  # type: ignore[arg-type]
        return provider_context


def _context() -> AgentHookContext:
    return AgentHookContext(iteration=1, messages=[])


def test_default_hook_returns_provider_context_unmodified() -> None:
    hook = AgentHook()
    ctx = _context()
    pc = ProviderCallContext(session_id="s1")
    assert hook.adjust_provider_context(ctx, pc) is pc


def test_composite_chains_multiple_hooks() -> None:
    hook = CompositeHook([
        _StubHook(None),
        _StubHook("long"),
    ])
    ctx = _context()
    pc = ProviderCallContext(session_id="s1")
    result = hook.adjust_provider_context(ctx, pc)
    assert result.session_id == "s1"
    assert result.cache_retention == "long"


def test_composite_isolates_failing_hook() -> None:
    hook = CompositeHook([
        _StubHook("long"),
        _StubHook(raises=True),
    ])
    ctx = _context()
    pc = ProviderCallContext(session_id="s1")
    result = hook.adjust_provider_context(ctx, pc)
    assert result.cache_retention == "long"

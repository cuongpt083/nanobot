"""Hook-provided run continuation: first non-empty wins, errors are isolated."""

from __future__ import annotations

from nanobot.agent.hook import AgentHook, CompositeHook


class _Stub(AgentHook):
    def __init__(self, text: str | None = None, *, raises: bool = False) -> None:
        super().__init__()
        self._text = text
        self._raises = raises

    def continuation(self) -> str | None:
        if self._raises:
            raise RuntimeError("boom")
        return self._text


def test_default_hook_has_no_continuation() -> None:
    assert AgentHook().continuation() is None


def test_composite_returns_the_first_non_empty_text() -> None:
    hook = CompositeHook([_Stub(None), _Stub("first"), _Stub("second")])
    assert hook.continuation() == "first"


def test_composite_isolates_a_failing_hook() -> None:
    hook = CompositeHook([_Stub(raises=True), _Stub("later")])
    assert hook.continuation() == "later"


def test_composite_without_hooks_returns_none() -> None:
    assert CompositeHook([]).continuation() is None

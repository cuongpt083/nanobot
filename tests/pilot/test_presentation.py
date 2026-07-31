"""Tests for server-side presentation policy."""


import pytest

from nanobot.pilot.presentation import PresentationPolicy


def _create_policy():
    counter = {"presentation_leak_prevented_total": 0}
    def _inc():
        counter["presentation_leak_prevented_total"] += 1
    return PresentationPolicy(on_leak_prevented=_inc), counter

@pytest.mark.parametrize("content", [
    "Here is some text <think>this is reasoning</think> and more text.",
    "<think>unclosed reasoning block",
    "Bearer sk-test-12345",
    "API-key: sk-123456",
    "C:\\Users\\Admin\\Workspaces\\nanobot\\secret.txt",
    "/var/run/secrets/kubernetes.io",
    "Exception: File not found",
])
def test_presentation_sanitizes_content(content):
    policy, counter = _create_policy()
    res = policy.sanitize(content, {})
    assert "sk-" not in res.content
    assert "<think>" not in res.content
    assert "reasoning" not in res.content
    assert "Exception" not in res.content
    assert "C:\\Users" not in res.content
    assert "kubernetes.io" not in res.content
    assert counter["presentation_leak_prevented_total"] == 1
    assert res.leak_prevented is True

@pytest.mark.parametrize("metadata, expected_dropped", [
    ({"reasoning_content": "secret"}, "reasoning_content"),
    ({"thinking_blocks": ["secret"]}, "thinking_blocks"),
    ({"tool_arguments": {"arg": "val"}}, "tool_arguments"),
    ({"error": "Exception"}, "error"),
    ({"nested": {"reasoning_content": "secret"}}, "nested.reasoning_content"),
])
def test_presentation_sanitizes_metadata(metadata, expected_dropped):
    policy, counter = _create_policy()
    res = policy.sanitize("hello", metadata)
    # Check that it drops the forbidden keys
    def check_dropped(d):
        if isinstance(d, dict):
            assert "reasoning_content" not in d
            assert "thinking_blocks" not in d
            assert "tool_arguments" not in d
            assert "error" not in d
            for v in d.values():
                check_dropped(v)

    check_dropped(res.metadata)
    assert counter["presentation_leak_prevented_total"] == 1
    assert res.leak_prevented is True

def test_presentation_allows_safe_content():
    policy, counter = _create_policy()
    res = policy.sanitize("Hello world!", {"normal_key": "val"})
    assert res.content == "Hello world!"
    assert res.metadata == {"normal_key": "val"}
    assert counter["presentation_leak_prevented_total"] == 0
    assert res.leak_prevented is False

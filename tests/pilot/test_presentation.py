"""Tests for server-side presentation policy."""

from copy import deepcopy

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
    "Bearer token-value",
    "API-key: token-value",
    "api_key=token-value",
    "cookie: session=value",
    "-----BEGIN PRIVATE KEY-----private material-----END PRIVATE KEY-----",
    "private_key=token-value",
    "https://user:password@example.test/private",
    "C:\\Users\\Admin\\Workspaces\\nanobot\\secret.txt",
    "/var/run/secrets/kubernetes.io",
    "Exception: File not found",
])
def test_presentation_sanitizes_content(content):
    policy, counter = _create_policy()
    res = policy.sanitize(content, {})
    assert "token-value" not in res.content
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
    ({"provider_error": {"message": "secret"}}, "provider_error"),
    ({"arguments": {"token": "secret"}}, "arguments"),
    ({"toolArguments": {"token": "secret"}}, "toolArguments"),
    ({"reasoning": "secret"}, "reasoning"),
    ({"reasoningDelta": "secret"}, "reasoningDelta"),
    ({"reasoning_end": "secret"}, "reasoning_end"),
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
    observed_keys: set[str] = set()

    def collect_keys(value):
        if isinstance(value, dict):
            observed_keys.update(value)
            for child in value.values():
                collect_keys(child)
        elif isinstance(value, list):
            for child in value:
                collect_keys(child)

    collect_keys(res.metadata)
    assert expected_dropped.rsplit(".", 1)[-1] not in observed_keys
    assert counter["presentation_leak_prevented_total"] == 1
    assert res.leak_prevented is True


def test_presentation_recursively_redacts_metadata_without_mutating_input():
    policy, counter = _create_policy()
    metadata = {
        "nested": {
            "list": [
                "Bearer nested-token",
                "api_key=nested-token",
                "cookie: nested-token",
                "private_key=nested-token",
                {"windowsPath": "C:\\Users\\Admin\\secret.txt"},
                {"url": "https://user:password@example.test/private"},
                {"think": "<think>unclosed reasoning"},
            ],
            "posixPath": "/var/run/secrets/kubernetes.io",
        }
    }
    original = deepcopy(metadata)

    result = policy.sanitize("safe", metadata)

    assert metadata == original
    assert result.metadata is not metadata
    assert result.metadata["nested"] is not metadata["nested"]
    assert "nested-token" not in str(result.metadata)
    assert "C:\\Users" not in str(result.metadata)
    assert "user:password" not in str(result.metadata)
    assert "kubernetes.io" not in str(result.metadata)
    assert "<think>" not in str(result.metadata)
    assert counter["presentation_leak_prevented_total"] == 1

def test_presentation_allows_safe_content():
    policy, counter = _create_policy()
    res = policy.sanitize("Hello world!", {"normal_key": "val"})
    assert res.content == "Hello world!"
    assert res.metadata == {"normal_key": "val"}
    assert counter["presentation_leak_prevented_total"] == 0
    assert res.leak_prevented is False

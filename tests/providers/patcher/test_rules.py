"""Tests for the data-driven patcher rule engine."""

from __future__ import annotations

from nanobot.providers.patcher.rules import (
    DEFAULT_CC_VERSION,
    PatcherConfig,
    PatcherRule,
    apply_rules,
    build_tool_name_maps,
    builtin_rules,
    compare_versions,
    default_config,
    merge_config,
    resolve_claude_code_version,
)


def _rule(**kwargs: object) -> PatcherRule:
    data: dict[str, object] = {"id": "r", "category": "system", "find": "a", "replace": "b"}
    data.update(kwargs)
    return PatcherRule(**data)  # type: ignore[arg-type]


def test_apply_rules_replaces_all_occurrences() -> None:
    rule = _rule(find="cat", replace="dog")
    assert apply_rules("cat cat catalog", [rule]) == "dog dog dogalog"


def test_apply_rules_ignores_disabled_and_empty_find() -> None:
    disabled = _rule(id="d", enabled=False, find="x", replace="y")
    empty = _rule(id="e", find="", replace="y")
    assert apply_rules("x", [disabled, empty]) == "x"


def test_apply_rules_specific_before_broad() -> None:
    rules = [
        _rule(id="specific", find="HEARTBEAT.md", replace="HEALTHCHECK.md"),
        _rule(id="broad", find="HEARTBEAT", replace="HEALTHCHECK"),
    ]
    assert apply_rules("HEARTBEAT.md", rules) == "HEALTHCHECK.md"


def test_apply_rules_regex_and_invalid_regex_skipped() -> None:
    regex = _rule(id="re", is_regex=True, flags="g", find=r"\bsubagents\b", replace="Subagents")
    assert apply_rules("the subagents run", [regex]) == "the Subagents run"

    bad = _rule(id="bad", is_regex=True, find="(", replace="x")
    assert apply_rules("unchanged", [bad]) == "unchanged"


def test_apply_rules_regex_case_insensitive_flag() -> None:
    rule = _rule(id="re", is_regex=True, flags="gi", find="abc", replace="x")
    assert apply_rules("ABC abc", [rule]) == "x x"


def test_build_tool_name_maps_is_bidirectional() -> None:
    rules = [
        _rule(id="t1", category="tool_name", find="sessions_list", replace="Sessions_list"),
        _rule(id="t2", category="tool_name", find="memory_search", replace="Memory_search"),
        _rule(id="off", category="tool_name", enabled=False, find="a", replace="b"),
    ]
    request, response = build_tool_name_maps(rules)
    assert request == {"sessions_list": "Sessions_list", "memory_search": "Memory_search"}
    assert response == {"Sessions_list": "sessions_list", "Memory_search": "memory_search"}
    for original, spoofed in request.items():
        assert response[spoofed] == original


def test_compare_versions_numeric_order() -> None:
    assert compare_versions("2.1.280", "2.1.258") > 0
    assert compare_versions("2.1.251", "2.1.258") < 0
    assert compare_versions("2.1.1", "2.1.1") == 0
    assert compare_versions("custom-tag", "2.1.1") == 0


def test_resolve_claude_code_version_floor() -> None:
    assert resolve_claude_code_version("2.1.200", DEFAULT_CC_VERSION) == DEFAULT_CC_VERSION
    assert resolve_claude_code_version("2.2.0", DEFAULT_CC_VERSION) == "2.2.0"
    assert resolve_claude_code_version("custom-tag", DEFAULT_CC_VERSION) == "custom-tag"
    assert resolve_claude_code_version(None, DEFAULT_CC_VERSION) == DEFAULT_CC_VERSION


def test_default_config_is_disabled_with_builtin_rules() -> None:
    config = default_config()
    assert config.enabled is False
    assert config.port == 18793
    assert any(rule.builtin for rule in config.rules)


def test_merge_config_keeps_user_enabled_state_and_adds_new_rules() -> None:
    defaults = default_config()
    # User disabled one built-in and has one custom rule.
    stored = PatcherConfig(
        enabled=True,
        claude_code_version="2.1.10",  # below floor
        rules=[
            PatcherRule(
                id="sys-brand-upper",
                category="system",
                enabled=False,
                find="OpenClaw",
                replace="Claude Code",
                builtin=True,
            ),
            PatcherRule(
                id="user-rule",
                category="response",
                enabled=True,
                find="foo",
                replace="bar",
                builtin=False,
            ),
        ],
    )
    merged = merge_config(defaults, stored)

    assert merged.enabled is True
    assert merged.claude_code_version == DEFAULT_CC_VERSION  # floor enforced
    brand = next(rule for rule in merged.rules if rule.id == "sys-brand-upper")
    assert brand.enabled is False
    assert any(rule.id == "user-rule" for rule in merged.rules)
    # A shipped rule the user never touched is present and enabled.
    assert any(rule.id == "hdr-beta" and rule.enabled for rule in merged.rules)


def test_merge_config_migrates_legacy_port() -> None:
    defaults = default_config()
    merged = merge_config(defaults, PatcherConfig(port=18791))
    assert merged.port == 18793


def test_rule_dict_round_trip() -> None:
    rule = builtin_rules()[0]
    restored = PatcherRule.from_dict(rule.to_dict())
    assert restored == rule
    assert PatcherRule.from_dict({"id": 1}) is None


def test_render_template_supports_both_placeholder_forms() -> None:
    from nanobot.providers.patcher.rules import render_template

    assert (
        render_template("v={{version}} s={{sessionId}}", version="1.2", session_id="abc")
        == "v=1.2 s=abc"
    )
    # Legacy TypeScript-style placeholders remain accepted.
    assert render_template("v=${version}", version="1.2") == "v=1.2"

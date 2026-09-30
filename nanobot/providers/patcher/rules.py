"""Data-driven patch rules for the Anthropic OAuth patcher proxy.

The original implementation (AICoworker) treats every transformation as data —
an ``id``, a ``category``, a ``find`` pattern and a ``replace`` value — so the
patch surface can evolve without shipping new code. This module ports that
model to Python and keeps it free of I/O so it is trivially unit-testable.

Categories
----------
``system``    find/replace applied to each ``system[]`` text block.
``tool_name`` rename a tool; automatically reversed in response ``tool_use``
              blocks via :func:`build_tool_name_maps`.
``tool_desc`` find/replace applied to tool descriptions.
``response``  find/replace applied to response text / tool input (reverse patch).
``header``    find is a header name, replace is its value (empty string removes).

.. warning::
   The built-in rules deliberately omit a turnkey identity spoof by default?
   No — they mirror the upstream set so the engine can be studied faithfully.
   They are gated behind ``PatcherConfig.enabled`` (default ``False``). See the
   package docstring and ``docs/plan-anthropic-patcher-proxy.md`` section 0 for
   the terms-of-service implications.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal, cast

PatcherRuleCategory = Literal["system", "tool_name", "tool_desc", "response", "header"]

# ── Constants (recovered from aicoworker-2026.6.28) ──

DEFAULT_PATCHER_PORT = 18793
DEFAULT_TARGET_URL = "https://api.anthropic.com"

#: Claude Code version advertised to Anthropic's OAuth backend. Anthropic gates
#: new models by the spoofed client version, so this is an app-managed *floor*:
#: an update may raise it, and a persisted value must never pin it lower.
DEFAULT_CC_VERSION = "2.1.280"

#: Attribution header injected as ``system[0]``. ``{{version}}`` is substituted.
#: We use ``{{...}}`` (not ``${...}``) because nanobot's config loader treats
#: ``${NAME}`` as an environment-variable reference.
DEFAULT_ATTRIBUTION = (
    "x-anthropic-billing-header: cc_version={{version}}.a1b; "
    "cc_entrypoint=cli; cch=00000;"
)

# NOTE: context-1m-2025-08-07 is intentionally excluded — it triggers
# "long context requires extra usage" for OAuth subscribers.
DEFAULT_BETA_HEADERS = (
    "claude-code-20250219,oauth-2025-04-20,interleaved-thinking-2025-05-14,"
    "thinking-token-count-2026-05-13,context-management-2025-06-27,"
    "prompt-caching-scope-2026-01-05,mid-conversation-system-2026-04-07,"
    "advisor-tool-2026-03-01,advanced-tool-use-2025-11-20,effort-2025-11-24,"
    "afk-mode-2026-01-31,extended-cache-ttl-2025-04-11,cache-diagnosis-2026-04-07"
)

DEFAULT_USER_AGENT_TEMPLATE = "claude-cli/{{version}} (external, sdk-cli)"


def render_template(template: str, *, version: str = "", session_id: str = "") -> str:
    """Substitute ``{{version}}``/``{{sessionId}}`` (and legacy ``${...}``) placeholders.

    ``${...}`` is kept as an input alias for migration from the original
    TypeScript config, but the shipped defaults use ``{{...}}`` so nanobot's
    env-var resolver never mistakes a template for an environment reference.
    """

    return (
        template.replace("{{version}}", version)
        .replace("${version}", version)
        .replace("{{sessionId}}", session_id)
        .replace("${sessionId}", session_id)
    )


# ── Data model ──


@dataclass
class PatcherRule:
    """One find/replace rule applied by the patcher proxy."""

    id: str
    category: PatcherRuleCategory
    enabled: bool = True
    label: str = ""
    find: str = ""
    replace: str = ""
    is_regex: bool = False
    flags: str = "g"
    builtin: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "category": self.category,
            "enabled": self.enabled,
            "label": self.label,
            "find": self.find,
            "replace": self.replace,
            "isRegex": self.is_regex,
            "flags": self.flags,
            "builtin": self.builtin,
        }

    @classmethod
    def from_dict(cls, raw: object) -> PatcherRule | None:
        if not isinstance(raw, dict):
            return None
        data = cast(dict[str, object], raw)
        rule_id = data.get("id")
        category = data.get("category")
        if not isinstance(rule_id, str) or not isinstance(category, str):
            return None
        if category not in ("system", "tool_name", "tool_desc", "response", "header"):
            return None
        find = data.get("find")
        replace = data.get("replace")
        flags = data.get("flags")
        return cls(
            id=rule_id,
            category=category,
            enabled=bool(data.get("enabled", True)),
            label=str(data.get("label", "")),
            find=find if isinstance(find, str) else "",
            replace=replace if isinstance(replace, str) else "",
            is_regex=bool(data.get("isRegex", False)),
            flags=flags if isinstance(flags, str) else "g",
            builtin=bool(data.get("builtin", False)),
        )


@dataclass
class PatcherConfig:
    """Runtime configuration for the patcher proxy."""

    enabled: bool = False
    port: int = DEFAULT_PATCHER_PORT
    target_base_url: str = DEFAULT_TARGET_URL
    claude_code_version: str = DEFAULT_CC_VERSION
    attribution_template: str = DEFAULT_ATTRIBUTION
    add_session_id: bool = True
    rules: list[PatcherRule] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "enabled": self.enabled,
            "port": self.port,
            "targetBaseUrl": self.target_base_url,
            "claudeCodeVersion": self.claude_code_version,
            "attributionTemplate": self.attribution_template,
            "addSessionId": self.add_session_id,
            "rules": [rule.to_dict() for rule in self.rules],
        }


# ── Version helpers ──


def _version_parts(value: str) -> list[int]:
    parts: list[int] = []
    for piece in value.split("."):
        if not piece.isdigit():
            return []
        parts.append(int(piece))
    return parts


def compare_versions(left: str, right: str) -> int:
    """Compare dotted numeric versions.

    Returns ``> 0`` when ``left`` is newer, ``< 0`` when older and ``0`` when
    equal *or when either side is not a plain dotted-numeric tag* (a custom tag
    must never be silently rewritten).
    """

    a = _version_parts(left)
    b = _version_parts(right)
    if not a or not b:
        return 0
    length = max(len(a), len(b))
    for index in range(length):
        x = a[index] if index < len(a) else 0
        y = b[index] if index < len(b) else 0
        if x != y:
            return x - y
    return 0


def resolve_claude_code_version(stored: str | None, shipped: str) -> str:
    """Keep the shipped version as a floor, but honour a higher/custom value."""

    if stored and compare_versions(stored, shipped) >= 0:
        return stored
    return shipped


# ── Rule application ──

_REGEX_FLAG_MAP: dict[str, int] = {
    "i": re.IGNORECASE,
    "m": re.MULTILINE,
    "s": re.DOTALL,
    "x": re.VERBOSE,
}


def _regex_flags(flags: str) -> int:
    result = 0
    for char in flags:
        result |= _REGEX_FLAG_MAP.get(char, 0)
    return result


def apply_rules(text: str, rules: list[PatcherRule]) -> str:
    """Apply every enabled rule in order (specific patterns should come first)."""

    result = text
    for rule in rules:
        if not rule.enabled or rule.find == "":
            continue
        if rule.is_regex:
            try:
                result = re.sub(
                    rule.find,
                    rule.replace,
                    result,
                    flags=_regex_flags(rule.flags),
                )
            except re.error:
                # A bad user pattern must never take down the proxy.
                continue
        else:
            result = result.replace(rule.find, rule.replace)
    return result


def rules_by_category(
    rules: list[PatcherRule], category: PatcherRuleCategory
) -> list[PatcherRule]:
    """Enabled rules of one category, preserving definition order."""

    return [rule for rule in rules if rule.category == category and rule.enabled]


def build_tool_name_maps(
    rules: list[PatcherRule],
) -> tuple[dict[str, str], dict[str, str]]:
    """Build ``(request_map, response_map)`` from enabled ``tool_name`` rules.

    ``request_map`` renames original → spoofed on the way out; ``response_map``
    reverses spoofed → original on the way back. The two are inverses only when
    the rename pairs are bijective — callers must not depend on collisions.
    """

    request_map: dict[str, str] = {}
    response_map: dict[str, str] = {}
    for rule in rules:
        if rule.category == "tool_name" and rule.enabled and rule.find:
            request_map[rule.find] = rule.replace
            response_map[rule.replace] = rule.find
    return request_map, response_map


# ── Default rules ──


def builtin_rules() -> list[PatcherRule]:
    """Fresh copy of the built-in rule set (mirrors AICoworker's defaults)."""

    return [
        # system prompt — branding / fingerprints
        PatcherRule(
            id="sys-remove-intro",
            category="system",
            label="Remove assistant intro sentence",
            find="You are a personal assistant running inside OpenClaw.",
            replace="",
            builtin=True,
        ),
        PatcherRule(
            id="sys-brand-upper",
            category="system",
            label="OpenClaw → Claude Code",
            find="OpenClaw",
            replace="Claude Code",
            builtin=True,
        ),
        PatcherRule(
            id="sys-brand-lower",
            category="system",
            label="openclaw → claude-code",
            find="openclaw",
            replace="claude-code",
            builtin=True,
        ),
        PatcherRule(
            id="sys-nanobot-upper",
            category="system",
            label="nanobot → Claude Code",
            find="nanobot",
            replace="Claude Code",
            builtin=True,
        ),
        PatcherRule(
            id="sys-nanobot-lower",
            category="system",
            label="Nanobot → Claude Code",
            find="Nanobot",
            replace="Claude Code",
            builtin=True,
        ),
        PatcherRule(
            id="sys-sessions-list",
            category="system",
            label="sessions_list → Sessions_list",
            find="sessions_list",
            replace="Sessions_list",
            builtin=True,
        ),
        PatcherRule(
            id="sys-sessions-send",
            category="system",
            label="sessions_send → Sessions_send",
            find="sessions_send",
            replace="Sessions_send",
            builtin=True,
        ),
        PatcherRule(
            id="sys-sessions-spawn",
            category="system",
            label="sessions_spawn → Sessions_spawn",
            find="sessions_spawn",
            replace="Sessions_spawn",
            builtin=True,
        ),
        PatcherRule(
            id="sys-sessions-yield",
            category="system",
            label="sessions_yield → Sessions_yield",
            find="sessions_yield",
            replace="Sessions_yield",
            builtin=True,
        ),
        PatcherRule(
            id="sys-sessions-history",
            category="system",
            label="sessions_history → Sessions_history",
            find="sessions_history",
            replace="Sessions_history",
            builtin=True,
        ),
        PatcherRule(
            id="sys-heartbeat-ok",
            category="system",
            label="HEARTBEAT_OK → HEALTH_CHECK",
            find="HEARTBEAT_OK",
            replace="HEALTH_CHECK",
            builtin=True,
        ),
        PatcherRule(
            id="sys-heartbeat-md",
            category="system",
            label="HEARTBEAT.md → HEALTHCHECK.md",
            find="HEARTBEAT.md",
            replace="HEALTHCHECK.md",
            builtin=True,
        ),
        PatcherRule(
            id="sys-heartbeat-broad",
            category="system",
            label="HEARTBEAT → HEALTHCHECK",
            find="HEARTBEAT",
            replace="HEALTHCHECK",
            builtin=True,
        ),
        PatcherRule(
            id="sys-reply-current",
            category="system",
            label="reply_to_current → reply_current",
            find="reply_to_current",
            replace="reply_current",
            builtin=True,
        ),
        PatcherRule(
            id="sys-reply-colon",
            category="system",
            label="reply_to: → reply_id:",
            find="reply_to:",
            replace="reply_id:",
            builtin=True,
        ),
        PatcherRule(
            id="sys-memory-search",
            category="system",
            label="memory_search → Memory_search",
            find="memory_search",
            replace="Memory_search",
            builtin=True,
        ),
        PatcherRule(
            id="sys-memory-get",
            category="system",
            label="memory_get → Memory_get",
            find="memory_get",
            replace="Memory_get",
            builtin=True,
        ),
        PatcherRule(
            id="sys-subagents",
            category="system",
            label="subagents → Subagents",
            find=r"\bsubagents\b",
            replace="Subagents",
            is_regex=True,
            flags="g",
            builtin=True,
        ),
        # tool names (auto-reversed in responses)
        PatcherRule(
            id="tool-sessions-list",
            category="tool_name",
            label="sessions_list → Sessions_list",
            find="sessions_list",
            replace="Sessions_list",
            builtin=True,
        ),
        PatcherRule(
            id="tool-sessions-send",
            category="tool_name",
            label="sessions_send → Sessions_send",
            find="sessions_send",
            replace="Sessions_send",
            builtin=True,
        ),
        PatcherRule(
            id="tool-sessions-spawn",
            category="tool_name",
            label="sessions_spawn → Sessions_spawn",
            find="sessions_spawn",
            replace="Sessions_spawn",
            builtin=True,
        ),
        PatcherRule(
            id="tool-sessions-yield",
            category="tool_name",
            label="sessions_yield → Sessions_yield",
            find="sessions_yield",
            replace="Sessions_yield",
            builtin=True,
        ),
        PatcherRule(
            id="tool-sessions-history",
            category="tool_name",
            label="sessions_history → Sessions_history",
            find="sessions_history",
            replace="Sessions_history",
            builtin=True,
        ),
        PatcherRule(
            id="tool-memory-search",
            category="tool_name",
            label="memory_search → Memory_search",
            find="memory_search",
            replace="Memory_search",
            builtin=True,
        ),
        PatcherRule(
            id="tool-memory-get",
            category="tool_name",
            label="memory_get → Memory_get",
            find="memory_get",
            replace="Memory_get",
            builtin=True,
        ),
        # tool descriptions
        PatcherRule(
            id="desc-brand-upper",
            category="tool_desc",
            label="OpenClaw → Claude Code (descriptions)",
            find="OpenClaw",
            replace="Claude Code",
            builtin=True,
        ),
        PatcherRule(
            id="desc-brand-lower",
            category="tool_desc",
            label="openclaw → claude-code (descriptions)",
            find="openclaw",
            replace="claude-code",
            builtin=True,
        ),
        # response reverse patch (specific before broad)
        PatcherRule(
            id="resp-reply-current",
            category="response",
            label="reply_current → reply_to_current",
            find="reply_current",
            replace="reply_to_current",
            builtin=True,
        ),
        PatcherRule(
            id="resp-reply-id",
            category="response",
            label="reply_id: → reply_to:",
            find="reply_id:",
            replace="reply_to:",
            builtin=True,
        ),
        PatcherRule(
            id="resp-health-check",
            category="response",
            label="HEALTH_CHECK → HEARTBEAT_OK",
            find="HEALTH_CHECK",
            replace="HEARTBEAT_OK",
            builtin=True,
        ),
        PatcherRule(
            id="resp-healthcheck-md",
            category="response",
            label="HEALTHCHECK.md → HEARTBEAT.md",
            find="HEALTHCHECK.md",
            replace="HEARTBEAT.md",
            builtin=True,
        ),
        PatcherRule(
            id="resp-healthcheck-broad",
            category="response",
            label="HEALTHCHECK → HEARTBEAT",
            find="HEALTHCHECK",
            replace="HEARTBEAT",
            builtin=True,
        ),
        PatcherRule(
            id="resp-memory-search",
            category="response",
            label="Memory_search → memory_search",
            find="Memory_search",
            replace="memory_search",
            builtin=True,
        ),
        PatcherRule(
            id="resp-memory-get",
            category="response",
            label="Memory_get → memory_get",
            find="Memory_get",
            replace="memory_get",
            builtin=True,
        ),
        PatcherRule(
            id="resp-subagents",
            category="response",
            label="Subagents → subagents",
            find=r"\bSubagents\b",
            replace="subagents",
            is_regex=True,
            flags="g",
            builtin=True,
        ),
        PatcherRule(
            id="resp-claude-code-path",
            category="response",
            label=".claude-code → .openclaw",
            find=".claude-code",
            replace=".openclaw",
            builtin=True,
        ),
        PatcherRule(
            id="resp-claude-code",
            category="response",
            label="claude-code → openclaw",
            find="claude-code",
            replace="openclaw",
            builtin=True,
        ),
        PatcherRule(
            id="resp-claude-code-branded",
            category="response",
            label="Claude Code → OpenClaw",
            find="Claude Code",
            replace="OpenClaw",
            builtin=True,
        ),
        # headers
        PatcherRule(
            id="hdr-user-agent",
            category="header",
            label="Set User-Agent to CLI format",
            find="user-agent",
            replace=DEFAULT_USER_AGENT_TEMPLATE,
            builtin=True,
        ),
        PatcherRule(
            id="hdr-beta",
            category="header",
            label="Set anthropic-beta to CLI values",
            find="anthropic-beta",
            replace=DEFAULT_BETA_HEADERS,
            builtin=True,
        ),
        PatcherRule(
            id="hdr-x-app",
            category="header",
            label="Set x-app: cli",
            find="x-app",
            replace="cli",
            builtin=True,
        ),
        PatcherRule(
            id="hdr-remove-accept",
            category="header",
            label="Remove accept header",
            find="accept",
            replace="",
            builtin=True,
        ),
        PatcherRule(
            id="hdr-remove-dangerous",
            category="header",
            label="Remove anthropic-dangerous-direct-browser-access",
            find="anthropic-dangerous-direct-browser-access",
            replace="",
            builtin=True,
        ),
    ]


def default_config() -> PatcherConfig:
    """A fresh default :class:`PatcherConfig`."""

    return PatcherConfig(rules=builtin_rules())


def merge_config(defaults: PatcherConfig, stored: PatcherConfig | None) -> PatcherConfig:
    """Overlay a persisted config onto the shipped defaults.

    Behaviour that protects users across app updates:

    * new built-in rules are always added;
    * a stored rule keeps its ``enabled`` flag and custom ``find``/``replace``;
    * non-built-in user rules are preserved;
    * ``claude_code_version`` is treated as a floor (see
      :func:`resolve_claude_code_version`).
    """

    if stored is None:
        return defaults

    merged = PatcherConfig(
        enabled=stored.enabled,
        port=defaults.port if stored.port == 18791 else stored.port,
        target_base_url=stored.target_base_url or defaults.target_base_url,
        claude_code_version=resolve_claude_code_version(
            stored.claude_code_version, defaults.claude_code_version
        ),
        attribution_template=stored.attribution_template or defaults.attribution_template,
        add_session_id=stored.add_session_id,
        rules=[],
    )

    stored_by_id = {rule.id: rule for rule in stored.rules}
    default_ids = {rule.id for rule in defaults.rules}

    for default_rule in defaults.rules:
        stored_rule = stored_by_id.get(default_rule.id)
        if stored_rule is None:
            merged.rules.append(default_rule)
            continue
        merged.rules.append(
            PatcherRule(
                id=default_rule.id,
                category=default_rule.category,
                enabled=stored_rule.enabled,
                label=default_rule.label,
                find=stored_rule.find,
                replace=stored_rule.replace,
                is_regex=default_rule.is_regex,
                flags=default_rule.flags,
                builtin=True,
            )
        )

    for stored_rule in stored.rules:
        if not stored_rule.builtin and stored_rule.id not in default_ids:
            merged.rules.append(stored_rule)

    return merged

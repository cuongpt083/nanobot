"""Anthropic OAuth patcher — data-driven request/response patch engine.

This package implements the *engine* half of the "Anthropic OAuth Patcher
Proxy": a set of serialisable find/replace rules (never executable code) that
transform outgoing Anthropic Messages-API requests and reverse-patch the
responses so the local runtime keeps working.

.. warning::
   The built-in default rules include identity/branding substitutions whose only
   purpose is to make a third-party client look like Anthropic's own Claude Code
   CLI. Using subscription OAuth tokens outside Anthropic's products violates
   Anthropic's terms of service; the legitimate choice for a third-party app is
   an Anthropic Console API key. See ``docs/plan-anthropic-patcher-proxy.md``
   section 0. Keep the spoof rules disabled unless you are doing a controlled,
   documented interoperability experiment on an account you own.
"""

from __future__ import annotations

from nanobot.providers.patcher.proxy import (
    AnthropicPatcherProxy,
    build_upstream_headers,
    collect_error_codes,
    describe_upstream_error,
    get_patcher_proxy,
    is_retryable_connect_error,
    reverse_full_response,
    reverse_sse_event,
    start_anthropic_patcher_proxy,
    stop_anthropic_patcher_proxy,
    transform_request,
    transform_system_blocks,
    transform_tools,
)
from nanobot.providers.patcher.rules import (
    DEFAULT_ATTRIBUTION,
    DEFAULT_BETA_HEADERS,
    DEFAULT_CC_VERSION,
    DEFAULT_PATCHER_PORT,
    DEFAULT_TARGET_URL,
    DEFAULT_USER_AGENT_TEMPLATE,
    PatcherConfig,
    PatcherRule,
    apply_rules,
    build_tool_name_maps,
    builtin_rules,
    compare_versions,
    default_config,
)
from nanobot.providers.patcher.sse import SseReframer, create_anthropic_sse_reframer

__all__ = [
    "DEFAULT_ATTRIBUTION",
    "DEFAULT_BETA_HEADERS",
    "DEFAULT_CC_VERSION",
    "DEFAULT_PATCHER_PORT",
    "DEFAULT_TARGET_URL",
    "DEFAULT_USER_AGENT_TEMPLATE",
    "AnthropicPatcherProxy",
    "PatcherConfig",
    "PatcherRule",
    "SseReframer",
    "apply_rules",
    "build_tool_name_maps",
    "build_upstream_headers",
    "builtin_rules",
    "collect_error_codes",
    "compare_versions",
    "create_anthropic_sse_reframer",
    "default_config",
    "describe_upstream_error",
    "get_patcher_proxy",
    "is_retryable_connect_error",
    "reverse_full_response",
    "reverse_sse_event",
    "start_anthropic_patcher_proxy",
    "stop_anthropic_patcher_proxy",
    "transform_request",
    "transform_system_blocks",
    "transform_tools",
]

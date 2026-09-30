"""Cache-aware payload optimizer (token saver that never busts a warm prompt cache).

Port of AICoworker's context-inspector trim/optimize to nanobot's single
OpenAI-style message format. Every transformation reshapes only the OUTGOING
payload (the session transcript is never modified) and follows one rule:

    A change that alters the cached prompt prefix is ADOPTED only when the
    provider cache is already cold (idle longer than its TTL). While warm, the
    previously adopted shape is re-applied verbatim so the prefix stays
    byte-identical and keeps hitting the cache.

Transformations (each individually switchable):
- block-aligned history trim: keep at most ``max_turns`` user turns, cutting
  whole blocks of ``max_turns // 2`` at user-turn boundaries;
- junk prune: trivial heartbeat/no-op exchanges, empty assistant stubs, failed
  tool round-trips; in-place shrink of one-shot heredoc scripts and mega results;
- agent-flagged waste (``mark_context_wasted`` tool call ids);
- system prompt freeze: a drifted system prompt is held back while warm.

Adopted decisions are keyed by message fingerprints, not indices, because
nanobot's consolidation can drop old history from the front at any time.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import time
from dataclasses import dataclass, field
from typing import Any

from loguru import logger

from nanobot.coworker.transcript import as_dict, content_text, tool_call_arguments, tool_calls

TRIVIAL_ACKS = frozenset({"", "HEARTBEAT_OK", "NO_REPLY", "REPLY_SKIP"})
HEREDOC_MIN = 1500
RESULT_MAX = 20_000
_HEREDOC = re.compile(r"<<-?\s*['\"]?[A-Za-z_]+")
_ERROR_HINT = "[Analyze the error above and try a different approach.]"

DEFAULT_TTL_S = 300.0


def fingerprint(message: dict[str, Any]) -> str:
    """Stable identity of a message within one session's history."""
    digest = hashlib.sha1()
    digest.update(str(message.get("role")).encode())
    digest.update(b"\0")
    digest.update(content_text(message.get("content"))[:2000].encode("utf-8", "replace"))
    for call in tool_calls(message):
        digest.update(b"\0call\0" + str(call.get("id")).encode())
    if message.get("tool_call_id"):
        digest.update(b"\0result\0" + str(message.get("tool_call_id")).encode())
    return digest.hexdigest()[:20]


@dataclass
class SessionCacheState:
    last_send: float = 0.0
    trim_anchor: str | None = None
    drop: frozenset[str] = frozenset()
    rewrite: frozenset[str] = frozenset()
    wasted_applied: frozenset[str] = frozenset()
    frozen_system: str | None = None
    frozen_since: float = 0.0
    history_head: str | None = None
    stats: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class OptimizePolicy:
    trim_enabled: bool
    max_turns: int
    optimize: bool
    freeze_system: bool
    freeze_max_hold_s: float
    ttl_s: float
    wasted_ids: frozenset[str] = frozenset()


_states: dict[str, SessionCacheState] = {}


def state_for(session_key: str) -> SessionCacheState:
    state = _states.get(session_key)
    if state is None:
        state = _states[session_key] = SessionCacheState()
    return state


def touch(session_key: str, at: float | None = None) -> None:
    """A keep-alive ping re-armed the cache without passing through a real send."""
    state_for(session_key).last_send = at if at is not None else time.time()


def reset_states() -> None:
    _states.clear()


def cache_ttl_seconds(override: int | None) -> float:
    """Short-TTL prompt caches (Anthropic ephemeral, OpenAI, Gemini) live ~5 minutes."""
    return float(override) if override else DEFAULT_TTL_S


# ---------- classification ----------

def _is_error_result(message: dict[str, Any]) -> bool:
    text = content_text(message.get("content")).lstrip()
    return text.startswith("Error") or _ERROR_HINT in text


def _last_turn_start(messages: list[dict[str, Any]]) -> int:
    for i in range(len(messages) - 1, -1, -1):
        if messages[i].get("role") == "user":
            return i
    return len(messages)


def classify_junk(messages: list[dict[str, Any]]) -> tuple[set[str], set[str]]:
    """(drop fingerprints, rewrite fingerprints) — the live turn is always protected."""
    drop: set[str] = set()
    rewrite: set[str] = set()
    limit = _last_turn_start(messages)
    results_by_call: dict[str, dict[str, Any]] = {}
    for m in messages[:limit]:
        if m.get("role") == "tool" and m.get("tool_call_id"):
            results_by_call[str(m["tool_call_id"])] = m

    for i in range(limit):
        m = messages[i]
        role = m.get("role")
        if role == "system":
            continue
        text = content_text(m.get("content")).strip()
        calls = tool_calls(m)

        # 1) no-op exchange: any user turn answered by a bare ack token.
        if role == "user" and i + 1 < limit:
            nxt = messages[i + 1]
            if (
                nxt.get("role") == "assistant"
                and not tool_calls(nxt)
                and content_text(nxt.get("content")).strip() in TRIVIAL_ACKS - {""}
            ):
                drop.update({fingerprint(m), fingerprint(nxt)})
                continue

        # 2) empty assistant stubs (aborted/error turns).
        if role == "assistant" and not calls and not text:
            drop.add(fingerprint(m))
            continue

        # 3) failed tool round-trip: a tool-only assistant message whose results all errored.
        if role == "assistant" and calls and not text:
            results = [results_by_call.get(str(c.get("id"))) for c in calls]
            if all(r is not None and _is_error_result(r) for r in results):
                drop.add(fingerprint(m))
                drop.update(fingerprint(r) for r in results if r is not None)
                continue

        # 4) in-place shrink (message kept, pairing intact).
        if role == "assistant" and any(_rewrite_args(tool_call_arguments(c)) for c in calls):
            rewrite.add(fingerprint(m))
        elif role == "tool" and len(content_text(m.get("content"))) > RESULT_MAX:
            rewrite.add(fingerprint(m))
    return drop, rewrite


def _rewrite_command(command: str) -> str | None:
    if len(command) <= HEREDOC_MIN or not _HEREDOC.search(command):
        return None
    head = command.split("\n", 1)[0][:400]
    return f"{head}\n…[auto-optimize: one-shot script body elided, {len(command)} chars]"


def _rewrite_args(arguments: str) -> str | None:
    if len(arguments) <= HEREDOC_MIN:
        return None
    try:
        parsed = as_dict(json.loads(arguments))
    except ValueError:
        return None
    command = parsed.get("command") if parsed is not None else None
    if parsed is None or not isinstance(command, str):
        return None
    shrunk = _rewrite_command(command)
    return json.dumps({**parsed, "command": shrunk}, ensure_ascii=False) if shrunk else None


def rewrite_message(message: dict[str, Any]) -> dict[str, Any]:
    """Deterministic shrink: same input → same output, so warm payloads stay identical."""
    if message.get("role") == "tool":
        text = content_text(message.get("content"))
        if len(text) > RESULT_MAX:
            elided = len(text) - 4500
            return {**message, "content": f"{text[:3000]}\n…[auto-optimize: {elided} chars elided]…\n{text[-1500:]}"}
        return message
    calls = tool_calls(message)
    if not calls:
        return message
    new_calls: list[dict[str, Any]] = []
    for call in calls:
        shrunk = _rewrite_args(tool_call_arguments(call))
        fn = as_dict(call.get("function"))
        if shrunk and fn is not None:
            call = {**call, "function": {**fn, "arguments": shrunk}}
        new_calls.append(call)
    return {**message, "tool_calls": new_calls}


def _drop_wasted(messages: list[dict[str, Any]], wasted: frozenset[str]) -> list[dict[str, Any]]:
    if not wasted:
        return messages
    limit = _last_turn_start(messages)
    out: list[dict[str, Any]] = []
    for i, m in enumerate(messages):
        if i >= limit:
            out.append(m)
        elif m.get("role") == "tool" and str(m.get("tool_call_id")) in wasted:
            continue
        elif m.get("role") == "assistant" and tool_calls(m):
            kept = [c for c in tool_calls(m) if str(c.get("id")) not in wasted]
            if len(kept) == len(tool_calls(m)):
                out.append(m)
            elif kept or content_text(m.get("content")).strip():
                out.append({**m, "tool_calls": kept} if kept else {k: v for k, v in m.items() if k != "tool_calls"})
        else:
            out.append(m)
    return out


# ---------- trim ----------

def _trim_cut(messages: list[dict[str, Any]], max_turns: int) -> int | None:
    """Block-aligned cut index (a user message), or None when within budget."""
    starts = [i for i, m in enumerate(messages) if m.get("role") == "user"]
    if len(starts) <= max_turns:
        return None
    block = max(1, max_turns // 2)
    drop_turns = math.ceil((len(starts) - max_turns) / block) * block
    if drop_turns >= len(starts):
        return None
    return starts[drop_turns]


def _apply_trim(messages: list[dict[str, Any]], anchor: str | None) -> tuple[list[dict[str, Any]], int]:
    if anchor is None:
        return messages, 0
    head = 0
    while head < len(messages) and messages[head].get("role") == "system":
        head += 1
    for i in range(head, len(messages)):
        if fingerprint(messages[i]) == anchor:
            return messages[:head] + messages[i:], i - head
    return messages, 0


# ---------- entry point ----------

def optimize_payload(
    session_key: str,
    messages: list[dict[str, Any]],
    policy: OptimizePolicy,
    *,
    now: float | None = None,
) -> list[dict[str, Any]]:
    """Return the payload to send; adopt new prefix changes only when the cache is cold."""
    state = state_for(session_key)
    now = time.time() if now is None else now
    cold = state.last_send == 0.0 or now - state.last_send > policy.ttl_s
    state.last_send = now
    out = list(messages)

    # System prompt freeze. When the history right after the system prompt changed
    # (compaction, consolidation, /new) the cached prefix is already gone, so the
    # new system prompt — which may carry the fresh summary — is adopted at once.
    head = fingerprint(out[1]) if len(out) > 1 else None
    history_rewritten = state.history_head is not None and head != state.history_head
    state.history_head = head
    if policy.freeze_system and out and out[0].get("role") == "system" and isinstance(out[0].get("content"), str):
        current = out[0]["content"]
        if state.frozen_system is None or current == state.frozen_system:
            state.frozen_system, state.frozen_since = current, state.frozen_since or now
        elif cold or history_rewritten or now - state.frozen_since > policy.freeze_max_hold_s:
            state.frozen_system, state.frozen_since = current, now
            logger.debug("coworker cache: adopted drifted system prompt for {}", session_key)
        else:
            out[0] = {**out[0], "content": state.frozen_system}
            state.stats["system_holds"] = state.stats.get("system_holds", 0) + 1

    if cold:
        # Re-decide junk/waste; nothing warm can be invalidated now.
        drop, rewrite = classify_junk(out) if policy.optimize else (set[str](), set[str]())
        state.drop, state.rewrite = frozenset(drop), frozenset(rewrite)
        state.wasted_applied = policy.wasted_ids

    if state.wasted_applied:
        out = _drop_wasted(out, state.wasted_applied)
    if state.drop or state.rewrite:
        limit = _last_turn_start(out)
        shaped: list[dict[str, Any]] = []
        for i, m in enumerate(out):
            fp = fingerprint(m) if i < limit else ""
            if fp and fp in state.drop:
                continue
            shaped.append(rewrite_message(m) if fp and fp in state.rewrite else m)
        out = shaped
    if not policy.trim_enabled:
        state.trim_anchor = None
    else:
        if cold:
            # Monotonic: the boundary only ever moves forward, and only while cold.
            current, _ = _apply_trim(out, state.trim_anchor)
            cut = _trim_cut(current, policy.max_turns)
            if cut is not None:
                state.trim_anchor = fingerprint(current[cut])
        if state.trim_anchor is not None:
            out, trimmed = _apply_trim(out, state.trim_anchor)
            if trimmed == 0 and not any(fingerprint(m) == state.trim_anchor for m in out):
                state.trim_anchor = None  # anchor consolidated away: history is already shorter
            state.stats["trimmed_messages"] = trimmed
    state.stats["sent_messages"] = len(out)
    state.stats["original_messages"] = len(messages)
    return out


def describe(session_key: str) -> dict[str, Any]:
    state = state_for(session_key)
    return {
        "idle_seconds": round(time.time() - state.last_send) if state.last_send else None,
        "trim_anchor": state.trim_anchor,
        "dropped": len(state.drop),
        "rewritten": len(state.rewrite),
        "wasted": len(state.wasted_applied),
        "system_frozen": state.frozen_system is not None,
        **state.stats,
    }


__all__ = [
    "OptimizePolicy",
    "cache_ttl_seconds",
    "classify_junk",
    "describe",
    "fingerprint",
    "optimize_payload",
    "reset_states",
    "rewrite_message",
    "state_for",
    "touch",
]

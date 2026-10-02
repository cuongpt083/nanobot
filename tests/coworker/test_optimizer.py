"""Cache-aware payload optimizer: prefix changes are adopted only while the cache is cold."""

from __future__ import annotations

import json

from nanobot.coworker.context import optimizer
from nanobot.coworker.context.optimizer import (
    OptimizePolicy,
    classify_junk,
    fingerprint,
    optimize_payload,
)

TTL = 300.0


def _policy(**overrides) -> OptimizePolicy:
    base = dict(
        trim_enabled=False, max_turns=4, optimize=False, freeze_system=False,
        freeze_max_hold_s=3600, ttl_s=TTL,
    )
    base.update(overrides)
    return OptimizePolicy(**base)


def _history(turns: int) -> list[dict]:
    messages = [{"role": "system", "content": "sys"}]
    for i in range(turns):
        messages += [{"role": "user", "content": f"u{i}"}, {"role": "assistant", "content": f"a{i}"}]
    return messages


def _users(messages: list[dict]) -> list[str]:
    return [m["content"] for m in messages if m["role"] == "user"]


def setup_function() -> None:
    optimizer.reset_states()


def test_trim_cuts_whole_blocks_at_user_boundaries_when_cold() -> None:
    out = optimize_payload("s", _history(7), _policy(trim_enabled=True, max_turns=4), now=1000)
    # 7 turns, cap 4, block 2 → drop ceil(3/2)*2 = 4 turns.
    assert out[0]["role"] == "system"
    assert _users(out) == ["u4", "u5", "u6"]


def test_trim_boundary_holds_while_cache_is_warm() -> None:
    policy = _policy(trim_enabled=True, max_turns=4)
    optimize_payload("s", _history(7), policy, now=1000)
    # Warm (10s later) with 3 more turns: the old cut is re-used verbatim.
    warm = optimize_payload("s", _history(10), policy, now=1010)
    assert _users(warm)[0] == "u4"
    # Cold again: the boundary advances (monotonic) — 6 kept turns > 4 → drop 2 more.
    cold = optimize_payload("s", _history(10), policy, now=1010 + TTL + 1)
    assert _users(cold) == ["u6", "u7", "u8", "u9"]


def test_trim_never_triggers_below_budget() -> None:
    out = optimize_payload("s", _history(3), _policy(trim_enabled=True, max_turns=4), now=1000)
    assert _users(out) == ["u0", "u1", "u2"]


def _tool_call(call_id: str, name: str = "exec", args: dict | None = None) -> dict:
    return {"id": call_id, "type": "function", "function": {"name": name, "arguments": json.dumps(args or {})}}


def test_classify_junk_protects_the_live_turn() -> None:
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "heartbeat"},
        {"role": "assistant", "content": "HEARTBEAT_OK"},
        {"role": "user", "content": "do x"},
        {"role": "assistant", "content": ""},
        {"role": "assistant", "content": None, "tool_calls": [_tool_call("c1")]},
        {"role": "tool", "tool_call_id": "c1", "name": "exec", "content": "Error: boom"},
        {"role": "assistant", "content": "done"},
        {"role": "user", "content": "live"},
        {"role": "assistant", "content": ""},
    ]
    drop, _ = classify_junk(messages)
    dropped = {i for i, m in enumerate(messages[:8]) if fingerprint(m) in drop}
    assert dropped == {1, 2, 4, 5, 6}
    sent = optimize_payload("s", messages, _policy(optimize=True), now=1000)
    assert sent == [messages[0], messages[3], messages[7], messages[8], messages[9]]


def test_heredoc_rewrite_is_deterministic_and_keeps_pairing() -> None:
    script = "cat > x.py <<'EOF'\n" + "print(1)\n" * 400 + "EOF"
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "write"},
        {"role": "assistant", "content": "", "tool_calls": [_tool_call("c1", args={"command": script})]},
        {"role": "tool", "tool_call_id": "c1", "name": "exec", "content": "ok"},
        {"role": "assistant", "content": "written"},
        {"role": "user", "content": "next"},
    ]
    policy = _policy(optimize=True)
    first = optimize_payload("s", messages, policy, now=1000)
    second = optimize_payload("s", messages, policy, now=1001)
    assert first == second
    args = json.loads(first[2]["tool_calls"][0]["function"]["arguments"])
    assert "script body elided" in args["command"]
    assert first[3]["tool_call_id"] == "c1"


def test_wasted_marks_apply_only_after_the_cache_goes_cold() -> None:
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "look"},
        {"role": "assistant", "content": "", "tool_calls": [_tool_call("c1", "grep")]},
        {"role": "tool", "tool_call_id": "c1", "name": "grep", "content": "huge dump"},
        {"role": "assistant", "content": "found it"},
        {"role": "user", "content": "next"},
    ]
    optimize_payload("s", messages, _policy(optimize=True), now=1000)
    warm = optimize_payload("s", messages, _policy(optimize=True, wasted_ids=frozenset({"c1"})), now=1010)
    assert len(warm) == len(messages)
    cold = optimize_payload("s", messages, _policy(optimize=True, wasted_ids=frozenset({"c1"})), now=2000)
    assert all(m.get("tool_call_id") != "c1" for m in cold)
    assert all(not m.get("tool_calls") for m in cold)


def test_system_prompt_drift_is_held_while_warm_and_adopted_when_cold() -> None:
    policy = _policy(freeze_system=True)
    base = [{"role": "system", "content": "v1"}, {"role": "user", "content": "hi"}]
    drifted = [{"role": "system", "content": "v2"}, {"role": "user", "content": "hi"}]
    optimize_payload("s", base, policy, now=1000)
    assert optimize_payload("s", drifted, policy, now=1010)[0]["content"] == "v1"
    assert optimize_payload("s", drifted, policy, now=1010 + TTL + 1)[0]["content"] == "v2"


def test_system_prompt_hold_is_bounded() -> None:
    policy = _policy(freeze_system=True, freeze_max_hold_s=60)
    optimize_payload("s", [{"role": "system", "content": "v1"}], policy, now=1000)
    held = optimize_payload("s", [{"role": "system", "content": "v2"}], policy, now=1030)
    adopted = optimize_payload("s", [{"role": "system", "content": "v2"}], policy, now=1100)
    assert held[0]["content"] == "v1" and adopted[0]["content"] == "v2"


def test_system_prompt_is_adopted_immediately_when_history_was_rewritten() -> None:
    policy = _policy(freeze_system=True)
    optimize_payload("s", [{"role": "system", "content": "v1"}, {"role": "user", "content": "old"}], policy, now=1000)
    compacted = [{"role": "system", "content": "v1 + summary"}, {"role": "user", "content": "new"}]
    assert optimize_payload("s", compacted, policy, now=1005)[0]["content"] == "v1 + summary"


def test_optimize_records_per_call_drop_and_send_counts() -> None:
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "heartbeat"},
        {"role": "assistant", "content": "HEARTBEAT_OK"},
        {"role": "user", "content": "real"},
        {"role": "assistant", "content": "answer"},
        {"role": "user", "content": "next"},
    ]
    optimize_payload("s", messages, _policy(optimize=True), now=1000)
    stats = optimizer.describe("s")
    assert stats["last_original_messages"] == 6
    assert stats["last_sent_messages"] == 4
    assert stats["last_dropped_messages"] == 2
    assert stats["last_rewritten_messages"] == 0


def test_optimize_records_per_call_trimmed_count() -> None:
    optimize_payload("s", _history(7), _policy(trim_enabled=True, max_turns=4), now=1000)
    stats = optimizer.describe("s")
    assert stats["last_trimmed_messages"] == 8
    assert stats["last_sent_messages"] == 7

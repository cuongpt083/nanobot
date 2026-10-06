"""Entry parsing for nanobot-bridge data returned by Pi's ``get_entries``."""

from __future__ import annotations

from nanobot.coworker.coding.pi import entries as pi_entries


def _custom(custom_type: str, data: dict) -> dict:
    return {"id": "x", "parentId": None, "type": "custom", "customType": custom_type, "data": data}


def test_extract_report_by_kind() -> None:
    entries = [
        _custom("nanobot_report", {"kind": "plan", "summary": "p"}),
        {"id": "m", "type": "message", "role": "assistant"},
        _custom("nanobot_report", {"kind": "implementation", "summary": "i"}),
    ]
    assert pi_entries.extract_report(entries, kind="plan")["summary"] == "p"
    assert pi_entries.extract_report(entries, kind="implementation")["summary"] == "i"
    assert pi_entries.extract_report(entries, kind="review") is None


def test_extract_report_returns_latest_matching() -> None:
    entries = [
        _custom("nanobot_report", {"kind": "implementation", "summary": "first"}),
        _custom("nanobot_report", {"kind": "implementation", "summary": "second"}),
    ]
    assert pi_entries.extract_report(entries, kind="implementation")["summary"] == "second"


def test_count_blocks_and_gate() -> None:
    entries = [
        _custom("nanobot_block", {"reason": "outside root"}),
        _custom("nanobot_block", {"reason": "git push"}),
        _custom("nanobot_gate", {"passed": False, "continuations": 2}),
    ]
    assert pi_entries.count_blocks(entries) == 2
    assert pi_entries.extract_gate(entries)["continuations"] == 2


def test_non_custom_entries_are_ignored() -> None:
    entries = [{"type": "message", "customType": "nanobot_report", "data": {"kind": "plan"}}]
    assert pi_entries.extract_report(entries, kind="plan") is None

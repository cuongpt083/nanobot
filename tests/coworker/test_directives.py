"""The full advisor directive: measured wording, nanobot tool names, byte-stable."""

from __future__ import annotations

import importlib

from nanobot.coworker import directives


def test_advisor_keeps_the_measured_sentences() -> None:
    text = directives.ADVISOR
    for phrase in (
        "calling advisor is the NEXT action",
        "err toward re-consulting",
        "This is a checkpoint, not a difficulty judgment",
        "which constraint breaks the tie",
        "Never treat that refusal as an error",
    ):
        assert phrase in text, phrase


def test_advisor_uses_nanobot_tool_names_and_plan_wording() -> None:
    text = directives.ADVISOR
    assert "(read_file, list_dir, find_files, rg/grep, web_fetch)" in text
    assert "create_goal for long multi-turn" in text
    assert "write_file / edit_file / apply_patch" in text
    assert "write_todos" not in text and "plan_task" not in text


def test_advisor_directive_is_byte_stable_across_builds() -> None:
    first = directives.ADVISOR
    assert importlib.reload(directives).ADVISOR == first


def test_user_requested_mention_note_says_it_will_not_be_refused() -> None:
    note = directives.advisor_mention_note(enabled=True)
    assert "user-requested" in note and "not be refused for thin context" in note

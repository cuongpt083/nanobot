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


def test_advisor_brainstorm_directive_wording() -> None:
    text = directives.ADVISOR_BRAINSTORM
    assert "consult the advisor on your draft before finalizing" in text
    assert "You may quote the advisor's key point in one short attributed line — never paste the whole advice." in text


def test_room_owner_lists_config_capability_highlights() -> None:
    from nanobot.coworker.config import RoomAgentConfig

    writer = RoomAgentConfig(
        id="writer",
        name="Writer",
        bio="writes copy",
        tools={"allow": ["mcp:crm:*", "read_file"]},
        skills={"inherit": ["cron", "weather"]},
    )
    researcher = RoomAgentConfig(id="researcher", name="Researcher", bio="finds facts")
    text = directives.room_owner([writer, researcher])
    assert "- `writer` — Writer: writes copy · crm, cron, weather" in text
    assert "- `researcher` — Researcher: finds facts" in text
    assert "mcp_crm" not in text

    extra = RoomAgentConfig(
        id="writer",
        name="Writer",
        bio="writes copy",
        tools={"allow": ["mcp:z:*", "mcp:a:*", "mcp:m:*", "mcp:b:*"]},
        skills={"inherit": ["weather", "cron"]},
    )
    capped = directives.room_owner([extra])
    assert " · a, b, cron, m, weather" in capped
    assert "z" not in capped.split(" · ", 1)[1]

    empty = RoomAgentConfig(id="plain", name="Plain")
    with_bio = RoomAgentConfig(id="writer", name="Writer", bio="writes copy")
    empty_text = directives.room_owner([empty])
    bio_text = directives.room_owner([with_bio])
    assert "- `plain` — Plain\n" in empty_text
    assert "- `writer` — Writer: writes copy\n" in bio_text
    assert " · " not in empty_text
    assert " · " not in bio_text

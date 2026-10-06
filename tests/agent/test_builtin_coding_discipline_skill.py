from pathlib import Path

from nanobot.agent.skills import (
    BUILTIN_SKILLS_DIR,
    SkillsLoader,
    parse_skill_metadata,
    valid_skill_metadata,
)

_SKILL = BUILTIN_SKILLS_DIR / "coding-discipline" / "SKILL.md"


def test_coding_discipline_frontmatter_is_valid() -> None:
    metadata = parse_skill_metadata(_SKILL.read_text(encoding="utf-8"))

    assert metadata is not None
    assert valid_skill_metadata(metadata, "coding-discipline")


def test_coding_discipline_is_listed_as_builtin(tmp_path: Path) -> None:
    entries = SkillsLoader(tmp_path).list_skills(filter_unavailable=False)

    match = [e for e in entries if e["name"] == "coding-discipline"]
    assert len(match) == 1
    assert match[0]["source"] == "builtin"


def test_coding_discipline_stays_compact_and_keeps_core_rules() -> None:
    content = _SKILL.read_text(encoding="utf-8")

    assert len(content.splitlines()) <= 60
    assert "root cause" in content.lower()
    assert "fresh evidence" in content
    assert "`advisor`" in content
    assert "coding_agent" in content

"""Tests verifying Phase 0 baseline fixtures and consistency."""

from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory

import yaml

from nanobot.session.manager import SessionManager
from scripts.gen_chat_fixture import generate_fixture

FIXTURE_PATH = (
    Path(__file__).resolve().parents[3] / "docs" / "coworker" / "plans" / "chat-300-fixture.jsonl"
)
RECALL_QUERIES_PATH = Path(__file__).resolve().parents[1] / "eval" / "recall_queries.yaml"
REPEAT_TASKS_PATH = Path(__file__).resolve().parents[1] / "eval" / "repeat_tasks.yaml"


def test_fixture_determinism_and_loadable(tmp_path: Path) -> None:
    assert FIXTURE_PATH.is_file(), f"Fixture file missing: {FIXTURE_PATH}"

    # Verify fixture loads through JsonlSessionStore and SessionManager without errors
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()
    sessions_root = tmp_path / "sessions_root"
    sessions_root.mkdir()

    manager = SessionManager(workspace=workspace_dir, sessions_root=sessions_root)
    session_key = "eval:desktop-perf-p0:chat-300"
    target_path = manager._get_session_path(session_key)

    # Copy fixture into session storage
    target_path.write_text(FIXTURE_PATH.read_text(encoding="utf-8"), encoding="utf-8")

    # Use direct _load to ensure it reads the file and doesn't silently create an empty session
    session = manager._load(session_key)
    assert session is not None
    assert session.key == session_key
    assert len(session.messages) == 300
    assert session.metadata.get("eval_fixture") is True

    # Replay history check
    history = session.get_history()
    assert len(history) > 0


def test_fixture_structure_contents() -> None:
    lines = [
        line.strip()
        for line in FIXTURE_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(lines) == 301  # 1 metadata header + 300 messages

    header = json.loads(lines[0])
    assert header.get("_type") == "metadata"

    messages = [json.loads(line) for line in lines[1:]]
    assert len(messages) == 300

    # Verify presence of diagrams
    content_all = "\n".join(m["content"] for m in messages)
    assert "participant ClientApp" in content_all
    assert "participant AuditLogger" in content_all
    # Check that sequence diagram has 15 participants
    participants = [
        "ClientApp",
        "Gateway",
        "AuthService",
        "UserStore",
        "RoomManager",
        "AgentScheduler",
        "ContextService",
        "RecallFTS",
        "LLMProvider",
        "ToolExecutor",
        "SandboxWorker",
        "FileSystem",
        "ArtifactStore",
        "EventBus",
        "AuditLogger",
    ]
    for p in participants:
        assert f"participant {p}" in content_all

    assert "flowchart TD" in content_all
    assert "stateDiagram-v2" in content_all


def test_recall_queries_consistency() -> None:
    with open(RECALL_QUERIES_PATH, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    queries = data.get("queries", [])
    assert len(queries) >= 15

    fixture_text = FIXTURE_PATH.read_text(encoding="utf-8")

    for q in queries:
        fact_id = q["expected_fact_id"]
        assert f"[{fact_id}]" in fixture_text, (
            f"Fact ID {fact_id} from {q['id']} not found in fixture"
        )
        for kw in q.get("expected_keywords", []):
            assert kw in fixture_text, f"Keyword '{kw}' for query {q['id']} not found in fixture"


def test_repeat_tasks_consistency() -> None:
    with open(REPEAT_TASKS_PATH, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    tasks = data.get("tasks", [])
    assert len(tasks) >= 5

    positives = [t for t in tasks if t.get("should_draft") is True]
    negatives = [t for t in tasks if t.get("should_draft") is False]

    assert len(positives) >= 2, "Must have at least 2 positive test cases"
    assert len(negatives) >= 2, "Must have at least 2 negative test cases"


def test_generator_deterministic_match() -> None:
    with TemporaryDirectory() as tmp_dir:
        generated_tmp = Path(tmp_dir) / "fixture.jsonl"
        generate_fixture(generated_tmp)
        assert generated_tmp.read_text(encoding="utf-8") == FIXTURE_PATH.read_text(encoding="utf-8")

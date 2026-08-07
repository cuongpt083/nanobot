"""Tests for pilot data export and curation pipeline."""

import json
from pathlib import Path

from nanobot.pilot.store import SQLitePilotStore
from nanobot.pilot.types import CapturePriority, ConsentState, QueueEvent
from scripts.pilot_curate import curate_dataset
from scripts.pilot_export import export_pilot_data


def test_export_and_curation_pipeline(tmp_path: Path) -> None:
    db_file = tmp_path / "test_export.db"
    export_jsonl = tmp_path / "exported.jsonl"
    cursor_file = tmp_path / "cursor.json"
    curated_dir = tmp_path / "curated"

    store = SQLitePilotStore(db_file)

    # Save consent for user 1 (eligible) and user 2 (ineligible)
    user1_pseudo = "u1_hash"
    user2_pseudo = "u2_hash"

    store.save_consent(
        ConsentState(
            user_pseudonym=user1_pseudo,
            product_allowed=True,
            product_version="v1",
            training_allowed=True,
            training_version="v1",
            created_at_ms=100,
            updated_at_ms=100,
        )
    )

    store.save_consent(
        ConsentState(
            user_pseudonym=user2_pseudo,
            product_allowed=True,
            product_version="v1",
            training_allowed=False,
            training_version="v1",
            created_at_ms=100,
            updated_at_ms=100,
        )
    )

    # Insert turn 1 (user 1, eligible)
    store.write_batch(
        [
            QueueEvent(
                event_id="e1",
                priority=CapturePriority.FINAL,
                kind="turn",
                payload={
                    "turn_id": "turn_1",
                    "user_pseudonym": user1_pseudo,
                    "session_pseudonym": "sess_1",
                    "channel": "webui",
                    "chat_id": "c1",
                    "routing_decision": {"route_class": "reasoning"},
                },
                created_at_ms=1000,
            ),
            QueueEvent(
                event_id="a1",
                priority=CapturePriority.ARTIFACT,
                kind="artifact",
                payload={
                    "turn_id": "turn_1",
                    "prompt_text": "Calculate 2+2",
                    "answer_text": "The answer is 4",
                },
                created_at_ms=1000,
            ),
        ]
    )

    # Insert turn 2 (user 2, ineligible)
    store.write_batch(
        [
            QueueEvent(
                event_id="e2",
                priority=CapturePriority.FINAL,
                kind="turn",
                payload={
                    "turn_id": "turn_2",
                    "user_pseudonym": user2_pseudo,
                    "session_pseudonym": "sess_2",
                    "channel": "webui",
                    "chat_id": "c2",
                },
                created_at_ms=2000,
            )
        ]
    )

    # Run export
    count = export_pilot_data(
        db_path=db_file,
        output_jsonl=export_jsonl,
        cursor_file=cursor_file,
    )
    assert count == 2

    # Verify JSONL records created
    with open(export_jsonl, "r") as f:
        rows = [json.loads(line) for line in f]
        assert len(rows) == 2
        assert rows[0]["training_eligible"] is True
        assert rows[1]["training_eligible"] is False

    # Run curation
    summary = curate_dataset(input_jsonl=export_jsonl, output_dir=curated_dir)
    assert summary["total_eligible"] == 1
    assert summary["total_ineligible"] == 1
    assert summary["unique_curated"] == 1

    store.close()

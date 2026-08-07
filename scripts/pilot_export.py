#!/usr/bin/env python3
"""Incremental, consent-gated export script from SQLite pilot event store to JSONL."""

from __future__ import annotations

import argparse
import json
import sqlite3
import time
from pathlib import Path

from nanobot.pilot.redaction import Redactor


def export_pilot_data(
    db_path: Path | str,
    output_jsonl: Path | str,
    cursor_file: Path | str = "~/.nanobot/pilot/export_cursor.json",
    since_turn_id: str | None = None,
    limit: int = 500,
) -> int:
    """Export turns and artifacts from SQLite store to JSONL with redaction defense-in-depth."""
    db_file = Path(db_path).expanduser()
    out_file = Path(output_jsonl).expanduser()
    cursor_path = Path(cursor_file).expanduser()

    if not db_file.exists():
        print(f"Database file not found: {db_file}")
        return 0

    out_file.parent.mkdir(parents=True, exist_ok=True)
    cursor_path.parent.mkdir(parents=True, exist_ok=True)

    # Determine starting cursor
    last_turn_id = since_turn_id
    if not last_turn_id and cursor_path.exists():
        try:
            with open(cursor_path, "r", encoding="utf-8") as f:
                c_data = json.load(f)
                last_turn_id = c_data.get("last_turn_id")
        except Exception:
            last_turn_id = None

    conn = sqlite3.connect(db_file)
    conn.row_factory = sqlite3.Row

    # Redactor for defense-in-depth (excluding tool_argument rule so tool patterns remain)
    redactor = Redactor()

    query = """
    SELECT
        t.turn_id,
        t.channel,
        json_extract(t.routing_decision, '$.route_class') AS route_class,
        json_extract(t.routing_decision, '$.reason_code') AS reason_code,
        a.prompt_text       AS prompt,
        a.reasoning_text    AS reasoning,
        a.answer_text       AS answer,
        a.tool_trajectory,
        a.prompt_chars,
        a.reasoning_chars,
        a.answer_chars,
        a.consent_version,
        a.redaction_version,
        a.capture_policy,
        EXISTS(SELECT 1 FROM consents c WHERE c.user_pseudonym = t.user_pseudonym AND c.training_allowed = 1) AS training_eligible
    FROM turns t
    LEFT JOIN artifacts a ON a.turn_id = t.turn_id
    WHERE (? IS NULL OR t.turn_id > ?)
    ORDER BY t.turn_id
    LIMIT ?
    """

    cur = conn.execute(query, (last_turn_id, last_turn_id, limit))
    rows = cur.fetchall()

    exported_count = 0
    now_ms = int(time.time() * 1000)
    new_last_turn_id = last_turn_id

    with open(out_file, "a", encoding="utf-8") as out_f:
        for row in rows:
            t_id = row["turn_id"]
            new_last_turn_id = t_id

            # Sub-queries for attempts and feedback
            att_cur = conn.execute(
                "SELECT provider, model, latency_ms, error_class, retry_index, fallback_index FROM attempts WHERE turn_id = ?",
                (t_id,),
            )
            attempts = [dict(r) for r in att_cur.fetchall()]

            fb_cur = conn.execute(
                "SELECT kind, created_at_ms FROM feedback WHERE turn_id = ?",
                (t_id,),
            )
            feedback = [dict(r) for r in fb_cur.fetchall()]

            # Apply defense-in-depth redaction to prompt, reasoning, answer
            raw_prompt = row["prompt"] or ""
            raw_reasoning = row["reasoning"] or ""
            raw_answer = row["answer"] or ""

            redacted_prompt = redactor.redact_string(raw_prompt).data if raw_prompt else None
            redacted_reasoning = redactor.redact_string(raw_reasoning).data if raw_reasoning else None
            redacted_answer = redactor.redact_string(raw_answer).data if raw_answer else None

            record = {
                "turn_id": t_id,
                "channel": row["channel"],
                "route_class": row["route_class"] or "default",
                "reason_code": row["reason_code"] or "DEFAULT_ROUTE",
                "prompt": redacted_prompt,
                "reasoning": redacted_reasoning,
                "answer": redacted_answer,
                "tool_trajectory": row["tool_trajectory"],
                "attempts": attempts,
                "feedback": feedback,
                "consent_version": row["consent_version"] or "pilot-product-v1",
                "redaction_version": row["redaction_version"] or "pilot-v1",
                "capture_policy": row["capture_policy"] or "metrics_only",
                "prompt_chars": row["prompt_chars"] or 0,
                "reasoning_chars": row["reasoning_chars"] or 0,
                "answer_chars": row["answer_chars"] or 0,
                "training_eligible": bool(row["training_eligible"]),
                "exported_at_ms": now_ms,
            }

            out_f.write(json.dumps(record) + "\n")
            exported_count += 1

    conn.close()

    if new_last_turn_id:
        with open(cursor_path, "w", encoding="utf-8") as f:
            json.dump({"last_turn_id": new_last_turn_id, "exported_at_ms": now_ms}, f, indent=2)

    return exported_count


def main() -> None:
    parser = argparse.ArgumentParser(description="Export pilot data from SQLite to JSONL")
    parser.add_argument("--db-path", default="~/.nanobot/pilot_events.db", help="SQLite database path")
    parser.add_argument("--output", default="~/.nanobot/pilot/exported_turns.jsonl", help="Output JSONL path")
    parser.add_argument("--cursor", default="~/.nanobot/pilot/export_cursor.json", help="Cursor state JSON path")
    parser.add_argument("--since-turn-id", default=None, help="Resume export from turn ID")
    parser.add_argument("--limit", type=int, default=500, help="Max records per export batch")
    args = parser.parse_args()

    count = export_pilot_data(
        db_path=args.db_path,
        output_jsonl=args.output,
        cursor_file=args.cursor,
        since_turn_id=args.since_turn_id,
        limit=args.limit,
    )
    print(f"Exported {count} turns to {args.output}")


if __name__ == "__main__":
    main()

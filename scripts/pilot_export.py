#!/usr/bin/env python3
"""Governed export pipeline from SQLite pilot store to JSONL."""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

from nanobot.pilot.redaction import Redactor


def export_pilot_data(
    db_path: Path | str,
    output_path: Path | str | None = None,
    cursor_path: Path | str | None = None,
    output_jsonl: Path | str | None = None,
    cursor_file: Path | str | None = None,
    since_turn_id: str | None = None,
    limit: int = 500,
) -> int:
    """Export turns from SQLite pilot store to governed JSONL."""
    out_p = output_jsonl if output_jsonl is not None else (output_path or "~/.nanobot/pilot/exported_turns.jsonl")
    cur_p = cursor_file if cursor_file is not None else (cursor_path or "~/.nanobot/pilot/export_cursor.json")

    db_path = Path(db_path).expanduser()
    output_path_obj = Path(out_p).expanduser()
    cursor_path_obj = Path(cur_p).expanduser()

    if not db_path.exists():
        output_path_obj.parent.mkdir(parents=True, exist_ok=True)
        output_path_obj.touch()
        return 0

    # Load cursor if since_turn_id is not explicitly passed
    last_turn_id = since_turn_id
    if last_turn_id is None and cursor_path_obj.exists():
        try:
            with open(cursor_path_obj, "r", encoding="utf-8") as f:
                cursor_data = json.load(f)
                last_turn_id = cursor_data.get("last_turn_id")
        except Exception:
            last_turn_id = None

    last_turn_id = last_turn_id or ""

    # Redactor with all rules except "tool_argument"
    redactor = Redactor(rules=["email", "phone", "ipv4", "jwt", "auth_header", "credential_regex"])

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

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
    WHERE t.turn_id > ?
    ORDER BY t.turn_id
    LIMIT ?
    """

    cursor.execute(query, (last_turn_id, limit))
    rows = cursor.fetchall()

    output_path_obj.parent.mkdir(parents=True, exist_ok=True)

    exported_count = 0
    new_last_turn_id = last_turn_id

    with open(output_path_obj, "a", encoding="utf-8") as out_f:
        for r in rows:
            turn_id = r["turn_id"]

            # Attempts sub-query
            cursor.execute(
                """
                SELECT provider, model, latency_ms, error_class, retry_index, fallback_index
                FROM attempts
                WHERE turn_id = ?
                """,
                (turn_id,),
            )
            attempts_rows = [dict(att) for att in cursor.fetchall()]

            # Feedback sub-query
            cursor.execute(
                """
                SELECT kind, created_at_ms
                FROM feedback
                WHERE turn_id = ?
                """,
                (turn_id,),
            )
            feedback_rows = [dict(fb) for fb in cursor.fetchall()]

            prompt_redacted, _ = redactor.redact(r["prompt"] or "")
            reasoning_redacted = redactor.redact(r["reasoning"])[0] if r["reasoning"] else None
            answer_redacted, _ = redactor.redact(r["answer"] or "")

            tool_traj = r["tool_trajectory"]
            if isinstance(tool_traj, str) and tool_traj:
                tool_traj_redacted, _ = redactor.redact(tool_traj)
            else:
                tool_traj_redacted = tool_traj

            record = {
                "turn_id": turn_id,
                "channel": r["channel"],
                "route_class": r["route_class"],
                "reason_code": r["reason_code"],
                "prompt": prompt_redacted,
                "reasoning": reasoning_redacted,
                "answer": answer_redacted,
                "tool_trajectory": tool_traj_redacted,
                "attempts": attempts_rows,
                "feedback": feedback_rows,
                "consent_version": r["consent_version"] or "pilot-product-v1",
                "redaction_version": r["redaction_version"] or "pilot-redaction-v1",
                "capture_policy": r["capture_policy"] or "reasoning",
                "prompt_chars": r["prompt_chars"] or len(prompt_redacted),
                "reasoning_chars": r["reasoning_chars"] or (len(reasoning_redacted) if reasoning_redacted else 0),
                "answer_chars": r["answer_chars"] or len(answer_redacted),
                "training_eligible": bool(r["training_eligible"]),
                "exported_at_ms": 1712345678000,
            }

            out_f.write(json.dumps(record, ensure_ascii=False) + "\n")
            exported_count += 1
            new_last_turn_id = turn_id

    conn.close()

    if exported_count > 0:
        cursor_path_obj.parent.mkdir(parents=True, exist_ok=True)
        with open(cursor_path_obj, "w", encoding="utf-8") as f:
            json.dump({"last_turn_id": new_last_turn_id, "exported_at_ms": 1712345678000}, f)

    return exported_count


def main() -> None:
    parser = argparse.ArgumentParser(description="Export governed pilot data from SQLite store")
    parser.add_argument("--db-path", default="~/.nanobot/pilot_events.db", help="Path to SQLite pilot store")
    parser.add_argument("--output", default="~/.nanobot/pilot/exported_turns.jsonl", help="Output JSONL path")
    parser.add_argument("--cursor", default="~/.nanobot/pilot/export_cursor.json", help="Cursor JSON file path")
    parser.add_argument("--since-turn-id", default=None, help="Optional turn ID cursor override")
    parser.add_argument("--limit", type=int, default=500, help="Max rows to export per run")
    args = parser.parse_args()

    count = export_pilot_data(
        db_path=args.db_path,
        output_path=args.output,
        cursor_path=args.cursor,
        since_turn_id=args.since_turn_id,
        limit=args.limit,
    )
    print(f"Exported {count} rows to {args.output}")


if __name__ == "__main__":
    main()

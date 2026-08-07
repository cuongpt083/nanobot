"""SQLite WAL event store for pilot event storage, consent, and metrics."""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any

from nanobot.pilot.migrations import migrate
from nanobot.pilot.types import ConsentState, QueueEvent


class SQLitePilotStore:
    """Synchronous SQLite database driver using WAL mode."""

    def __init__(self, db_path: Path | str) -> None:
        self.db_path = str(db_path)
        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.execute("PRAGMA foreign_keys=ON;")
        migrate(self._conn)

    def close(self) -> None:
        self._conn.close()

    def write_batch(self, events: list[QueueEvent]) -> int:
        """Write a batch of QueueEvents atomically."""
        if not events:
            return 0

        written = 0
        with self._conn:
            for event in events:
                p = event.payload
                if event.kind == "turn":
                    self._conn.execute(
                        """
                        INSERT OR REPLACE INTO turns (
                            turn_id, user_pseudonym, session_pseudonym, channel, chat_id,
                            created_at_ms, consent_version, routing_decision,
                            store_prompt, store_reasoning, store_answer, training_eligible
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            p["turn_id"],
                            p["user_pseudonym"],
                            p["session_pseudonym"],
                            p["channel"],
                            p["chat_id"],
                            event.created_at_ms,
                            p.get("consent_version", "pilot-v1"),
                            json.dumps(p.get("routing_decision", {})),
                            int(p.get("store_prompt", False)),
                            int(p.get("store_reasoning", False)),
                            int(p.get("store_answer", False)),
                            int(p.get("training_eligible", False)),
                        ),
                    )
                    written += 1
                elif event.kind == "attempt":
                    self._conn.execute(
                        """
                        INSERT OR REPLACE INTO attempts (
                            attempt_id, turn_id, provider, model, latency_ms,
                            usage_json, error_class, retry_index, fallback_index
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            event.event_id,
                            p["turn_id"],
                            p["provider"],
                            p["model"],
                            p.get("latency_ms", 0),
                            json.dumps(p.get("usage", {})),
                            p.get("error_class"),
                            p.get("retry_index", 0),
                            p.get("fallback_index"),
                        ),
                    )
                    written += 1
                elif event.kind == "artifact":
                    self._conn.execute(
                        """
                        INSERT OR REPLACE INTO artifacts (
                            artifact_id, turn_id, prompt_text, reasoning_text, answer_text,
                            tool_trajectory, prompt_chars, reasoning_chars, answer_chars,
                            consent_version, redaction_version, capture_policy
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            event.event_id,
                            p["turn_id"],
                            p.get("prompt_text"),
                            p.get("reasoning_text"),
                            p.get("answer_text"),
                            json.dumps(p.get("tool_trajectory")) if p.get("tool_trajectory") else None,
                            p.get("prompt_chars", 0),
                            p.get("reasoning_chars", 0),
                            p.get("answer_chars", 0),
                            p.get("consent_version", "pilot-v1"),
                            p.get("redaction_version", "pilot-v1"),
                            p.get("capture_policy", "metrics_only"),
                        ),
                    )
                    written += 1
                elif event.kind == "feedback":
                    self._conn.execute(
                        """
                        INSERT OR REPLACE INTO feedback (
                            feedback_id, turn_id, user_pseudonym, kind, created_at_ms, metadata_json
                        ) VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            event.event_id,
                            p["turn_id"],
                            p["user_pseudonym"],
                            p["kind"],
                            event.created_at_ms,
                            json.dumps(p.get("metadata", {})),
                        ),
                    )
                    written += 1
                elif event.kind == "consent":
                    self._conn.execute(
                        """
                        INSERT OR REPLACE INTO consents (
                            user_pseudonym, product_allowed, product_version,
                            training_allowed, training_version, created_at_ms, updated_at_ms
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            p["user_pseudonym"],
                            int(p["product_allowed"]),
                            p["product_version"],
                            int(p["training_allowed"]),
                            p["training_version"],
                            event.created_at_ms,
                            event.created_at_ms,
                        ),
                    )
                    written += 1
        return written

    def get_ownership(self, turn_id: str) -> tuple[str, str] | None:
        cur = self._conn.execute(
            "SELECT user_pseudonym, session_pseudonym FROM turns WHERE turn_id = ?",
            (turn_id,),
        )
        row = cur.fetchone()
        if row:
            return (row["user_pseudonym"], row["session_pseudonym"])
        return None

    def get_consent(self, user_pseudonym: str) -> ConsentState | None:
        cur = self._conn.execute(
            "SELECT * FROM consents WHERE user_pseudonym = ?",
            (user_pseudonym,),
        )
        row = cur.fetchone()
        if not row:
            return None
        return ConsentState(
            user_pseudonym=row["user_pseudonym"],
            product_allowed=bool(row["product_allowed"]),
            product_version=row["product_version"],
            training_allowed=bool(row["training_allowed"]),
            training_version=row["training_version"],
            created_at_ms=row["created_at_ms"],
            updated_at_ms=row["updated_at_ms"],
        )

    def save_consent(self, consent: ConsentState) -> None:
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO consents (
                    user_pseudonym, product_allowed, product_version,
                    training_allowed, training_version, created_at_ms, updated_at_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_pseudonym) DO UPDATE SET
                    product_allowed=excluded.product_allowed,
                    product_version=excluded.product_version,
                    training_allowed=excluded.training_allowed,
                    training_version=excluded.training_version,
                    updated_at_ms=excluded.updated_at_ms
                """,
                (
                    consent.user_pseudonym,
                    int(consent.product_allowed),
                    consent.product_version,
                    int(consent.training_allowed),
                    consent.training_version,
                    consent.created_at_ms,
                    consent.updated_at_ms,
                ),
            )

    def get_turn_count(self, user_pseudonym: str) -> int:
        cur = self._conn.execute(
            "SELECT COUNT(*) FROM turns WHERE user_pseudonym = ?",
            (user_pseudonym,),
        )
        return cur.fetchone()[0]

    def delete_by_pseudonym(self, user_pseudonym: str) -> dict[str, int]:
        now_ms = int(time.time() * 1000)
        with self._conn:
            # Count rows to be deleted
            turns_c = self._conn.execute(
                "SELECT COUNT(*) FROM turns WHERE user_pseudonym = ?", (user_pseudonym,)
            ).fetchone()[0]
            attempts_c = self._conn.execute(
                "SELECT COUNT(*) FROM attempts WHERE turn_id IN (SELECT turn_id FROM turns WHERE user_pseudonym = ?)",
                (user_pseudonym,),
            ).fetchone()[0]
            artifacts_c = self._conn.execute(
                "SELECT COUNT(*) FROM artifacts WHERE turn_id IN (SELECT turn_id FROM turns WHERE user_pseudonym = ?)",
                (user_pseudonym,),
            ).fetchone()[0]
            feedback_c = self._conn.execute(
                "SELECT COUNT(*) FROM feedback WHERE user_pseudonym = ?", (user_pseudonym,)
            ).fetchone()[0]

            self._conn.execute("DELETE FROM turns WHERE user_pseudonym = ?", (user_pseudonym,))
            self._conn.execute("DELETE FROM feedback WHERE user_pseudonym = ?", (user_pseudonym,))
            self._conn.execute("DELETE FROM consents WHERE user_pseudonym = ?", (user_pseudonym,))

            del_id = uuid.uuid4().hex
            self._conn.execute(
                """
                INSERT INTO deletions (
                    deletion_id, user_pseudonym, requested_at_ms, completed_at_ms,
                    turn_count, attempt_count, artifact_count, feedback_count
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    del_id,
                    user_pseudonym,
                    now_ms,
                    now_ms,
                    turns_c,
                    attempts_c,
                    artifacts_c,
                    feedback_c,
                ),
            )

        return {
            "turn_count": turns_c,
            "attempt_count": attempts_c,
            "artifact_count": artifacts_c,
            "feedback_count": feedback_c,
        }

    def count_retention_candidates(self, now_ms: int, retention_days: int) -> dict[str, int]:
        cutoff_ms = now_ms - (retention_days * 86400 * 1000)
        cur = self._conn.execute(
            "SELECT COUNT(*) FROM turns WHERE created_at_ms < ?", (cutoff_ms,)
        )
        old_turns = cur.fetchone()[0]
        return {"old_turns": old_turns}

    def get_aggregate_metrics(self, since_ms: int) -> dict[str, Any]:
        cur = self._conn.execute(
            "SELECT COUNT(*) FROM turns WHERE created_at_ms >= ?", (since_ms,)
        )
        total_turns = cur.fetchone()[0]

        cur = self._conn.execute(
            "SELECT COUNT(*), AVG(latency_ms) FROM attempts WHERE turn_id IN (SELECT turn_id FROM turns WHERE created_at_ms >= ?)",
            (since_ms,),
        )
        row = cur.fetchone()
        total_attempts = row[0]
        avg_latency = row[1] or 0.0

        return {
            "total_turns": total_turns,
            "total_attempts": total_attempts,
            "avg_latency_ms": avg_latency,
        }

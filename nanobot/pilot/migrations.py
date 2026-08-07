"""Schema migrations for the pilot SQLite WAL store."""

from __future__ import annotations

import sqlite3
import time

CURRENT_VERSION = 1

_MIGRATION_V1 = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version     INTEGER PRIMARY KEY,
    applied_at  INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS turns (
    turn_id             TEXT PRIMARY KEY,
    user_pseudonym      TEXT NOT NULL,
    session_pseudonym   TEXT NOT NULL,
    channel             TEXT NOT NULL,
    chat_id             TEXT NOT NULL,
    created_at_ms       INTEGER NOT NULL,
    consent_version     TEXT NOT NULL,
    routing_decision    TEXT NOT NULL,
    store_prompt        INTEGER NOT NULL DEFAULT 0,
    store_reasoning     INTEGER NOT NULL DEFAULT 0,
    store_answer        INTEGER NOT NULL DEFAULT 0,
    training_eligible   INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_turns_user ON turns(user_pseudonym);
CREATE INDEX IF NOT EXISTS idx_turns_session ON turns(session_pseudonym);

CREATE TABLE IF NOT EXISTS attempts (
    attempt_id      TEXT PRIMARY KEY,
    turn_id         TEXT NOT NULL REFERENCES turns(turn_id) ON DELETE CASCADE,
    provider        TEXT NOT NULL,
    model           TEXT NOT NULL,
    latency_ms      INTEGER NOT NULL,
    usage_json      TEXT,
    error_class     TEXT,
    retry_index     INTEGER NOT NULL,
    fallback_index  INTEGER
);
CREATE INDEX IF NOT EXISTS idx_attempts_turn ON attempts(turn_id);

CREATE TABLE IF NOT EXISTS artifacts (
    artifact_id     TEXT PRIMARY KEY,
    turn_id         TEXT NOT NULL REFERENCES turns(turn_id) ON DELETE CASCADE,
    prompt_text     TEXT,
    reasoning_text  TEXT,
    answer_text     TEXT,
    tool_trajectory TEXT,
    prompt_chars    INTEGER NOT NULL DEFAULT 0,
    reasoning_chars INTEGER NOT NULL DEFAULT 0,
    answer_chars    INTEGER NOT NULL DEFAULT 0,
    consent_version TEXT NOT NULL,
    redaction_version TEXT NOT NULL,
    capture_policy  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_artifacts_turn ON artifacts(turn_id);

CREATE TABLE IF NOT EXISTS feedback (
    feedback_id     TEXT PRIMARY KEY,
    turn_id         TEXT NOT NULL REFERENCES turns(turn_id) ON DELETE CASCADE,
    user_pseudonym  TEXT NOT NULL,
    kind            TEXT NOT NULL,
    created_at_ms   INTEGER NOT NULL,
    metadata_json   TEXT
);
CREATE INDEX IF NOT EXISTS idx_feedback_turn ON feedback(turn_id);
CREATE INDEX IF NOT EXISTS idx_feedback_user ON feedback(user_pseudonym);

CREATE TABLE IF NOT EXISTS consents (
    user_pseudonym  TEXT NOT NULL PRIMARY KEY,
    product_allowed INTEGER NOT NULL DEFAULT 0,
    product_version TEXT NOT NULL,
    training_allowed INTEGER NOT NULL DEFAULT 0,
    training_version TEXT NOT NULL,
    created_at_ms   INTEGER NOT NULL,
    updated_at_ms   INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS deletions (
    deletion_id     TEXT PRIMARY KEY,
    user_pseudonym  TEXT NOT NULL,
    requested_at_ms INTEGER NOT NULL,
    completed_at_ms INTEGER NOT NULL,
    turn_count      INTEGER NOT NULL,
    attempt_count   INTEGER NOT NULL,
    artifact_count  INTEGER NOT NULL,
    feedback_count  INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_deletions_user ON deletions(user_pseudonym);
"""


def _get_current_version(conn: sqlite3.Connection) -> int:
    try:
        cur = conn.execute("SELECT MAX(version) FROM schema_migrations")
        row = cur.fetchone()
        return row[0] if row and row[0] is not None else 0
    except sqlite3.OperationalError:
        return 0


def migrate(conn: sqlite3.Connection) -> None:
    """Apply pending database migrations in transaction."""
    current = _get_current_version(conn)
    if current >= CURRENT_VERSION:
        return

    now_ms = int(time.time() * 1000)
    with conn:
        if current < 1:
            conn.executescript(_MIGRATION_V1)
            conn.execute(
                "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
                (1, now_ms),
            )
            conn.execute("PRAGMA user_version = 1")

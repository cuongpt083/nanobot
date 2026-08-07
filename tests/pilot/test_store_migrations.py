"""Tests for SQLite database schema migrations."""

import sqlite3

from nanobot.pilot.migrations import CURRENT_VERSION, migrate


def test_migrations_fresh_db(tmp_path) -> None:
    db_file = tmp_path / "test_fresh.db"
    conn = sqlite3.connect(db_file)
    migrate(conn)

    cur = conn.execute("SELECT version FROM schema_migrations")
    assert cur.fetchone()[0] == CURRENT_VERSION

    # Check tables created
    cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = {row[0] for row in cur.fetchall()}
    expected = {"schema_migrations", "turns", "attempts", "artifacts", "feedback", "consents", "deletions"}
    assert expected.issubset(tables)

    conn.close()


def test_migrations_idempotent(tmp_path) -> None:
    db_file = tmp_path / "test_idempotent.db"
    conn = sqlite3.connect(db_file)
    migrate(conn)
    migrate(conn)  # second run should do nothing

    cur = conn.execute("SELECT COUNT(*) FROM schema_migrations")
    assert cur.fetchone()[0] == 1
    conn.close()

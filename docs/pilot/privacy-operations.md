# Pilot Privacy Operations & Runbook

## User Consent Management

Users manage their consent state using slash commands:
- `/consent status` — Display current consent settings.
- `/consent product on|off` — Opt in or out of product improvement capture.
- `/consent training on|off` — Opt in or out of fine-tuning dataset inclusion.

## Privacy Deletion Request

When a user requests privacy deletion:
- Command: `/privacy delete`
- Action: Atomically deletes turns, artifacts, feedback, and consents associated with the sender's pseudonym, and appends a content-free deletion audit record.

## SQLite Backup & Maintenance

- WAL mode enabled (`PRAGMA journal_mode=WAL;`).
- Backup strategy: Run `sqlite3 ~/.nanobot/pilot_events.db ".backup ~/.nanobot/pilot_events.db.bak"` while the service is live.

# Pilot Data Curation Pipeline

This document describes the governed data curation pipeline for exporting turns from the SQLite pilot store, redacting credentials, filtering user training consents, deduplicating records, and splitting into train/validation/test datasets.

## Pipeline Architecture

```
SQLite Pilot Store (~/.nanobot/pilot_events.db)
       │
       ▼
scripts/pilot_export.py (Cursor-based incremental export + Redactor)
       │
       ▼
Exported JSONL (~/.nanobot/pilot/exported_turns.jsonl)
       │
       ▼
scripts/pilot_curate.py (Consent filter + Deduplication + Quality heuristics)
       │
       ├── train.jsonl (80%)
       ├── val.jsonl   (10%)
       └── test.jsonl  (10%)
```

## Step 1: Exporting Data

Run `scripts/pilot_export.py` to read turns from the SQLite store. Cursor state is saved to `~/.nanobot/pilot/export_cursor.json` for incremental exports.

```bash
uv run python3 scripts/pilot_export.py --db-path ~/.nanobot/pilot_events.db --output ~/.nanobot/pilot/exported_turns.jsonl
```

## Step 2: Curating & Splitting Dataset

Run `scripts/pilot_curate.py` to filter `training_eligible == True` turns, deduplicate by `turn_id`, calculate quality metrics, and split deterministically (`random_state=42`).

```bash
uv run python3 scripts/pilot_curate.py --input ~/.nanobot/pilot/exported_turns.jsonl --output-dir ~/.nanobot/pilot/curated
```

## Data Governance & Privacy

1. **Consent Gating:** Only turns where `training_allowed == 1` in the `consents` table are marked `training_eligible: true` and included in the training sets.
2. **Defence-in-Depth Redaction:** All exported text (prompts, reasoning, answers, tool trajectories) is passed through `Redactor` to strip credentials, keys, bearer tokens, cookies, and local paths.

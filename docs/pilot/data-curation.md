# Pilot Data Curation & Dataset Pipeline

This document explains how captured events from the SQLite store are exported, filtered by user consent, redacted, and curated into fine-tuning datasets.

## Pipeline Overview

```
SQLite Pilot Store ──► pilot_export.py ──► exported_turns.jsonl ──► pilot_curate.py ──► train/val/test splits
```

## Export Script (`scripts/pilot_export.py`)

- Performs cursor-based incremental exports using `--since-turn-id` and writes status to `export_cursor.json`.
- Joins `turns`, `artifacts`, `attempts`, `feedback`, and `consents` tables.
- Evaluates `training_eligible` per turn based on whether the user has granted training consent (`training_allowed == 1`).
- Applies defense-in-depth redaction (`Redactor`) to prompt, reasoning, and answer text.

## Curation Script (`scripts/pilot_curate.py`)

- Filters out any rows where `training_eligible != true`.
- Deduplicates by `turn_id`.
- Splits data into `train.jsonl` (80%), `val.jsonl` (10%), and `test.jsonl` (10%) using deterministic hashing on `turn_id`.
- Output directory: `~/.nanobot/pilot/curated/`.

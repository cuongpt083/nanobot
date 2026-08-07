#!/usr/bin/env python3
"""Curate exported JSONL: filter consent, deduplicate, compute metrics, and split train/val/test."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def hash_split(turn_id: str) -> str:
    """Deterministically map a turn_id to 'train', 'val', or 'test' (80/10/10 split)."""
    digest = hashlib.md5(turn_id.encode("utf-8")).hexdigest()
    val = int(digest[:8], 16) % 100
    if val < 80:
        return "train"
    elif val < 90:
        return "val"
    else:
        return "test"


def curate_dataset(
    input_jsonl: Path | str,
    output_dir: Path | str = "~/.nanobot/pilot/curated/",
) -> dict[str, Any]:
    """Curate dataset: filter training_eligible, deduplicate, and split."""
    in_path = Path(input_jsonl).expanduser()
    out_dir = Path(output_dir).expanduser()

    if not in_path.exists():
        print(f"Input file not found: {in_path}")
        return {"total": 0}

    out_dir.mkdir(parents=True, exist_ok=True)

    seen_turns: set[str] = set()
    splits: dict[str, list[dict[str, Any]]] = {"train": [], "val": [], "test": []}

    total_eligible = 0
    total_ineligible = 0

    with open(in_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            turn_id = row.get("turn_id")

            if not row.get("training_eligible"):
                total_ineligible += 1
                continue

            total_eligible += 1

            if turn_id in seen_turns:
                continue
            seen_turns.add(turn_id)

            split = hash_split(turn_id)
            splits[split].append(row)

    # Write split JSONL files
    for split_name, rows in splits.items():
        split_file = out_dir / f"{split_name}.jsonl"
        with open(split_file, "w", encoding="utf-8") as out_f:
            for r in rows:
                out_f.write(json.dumps(r) + "\n")

    summary = {
        "total_eligible": total_eligible,
        "total_ineligible": total_ineligible,
        "unique_curated": len(seen_turns),
        "train_count": len(splits["train"]),
        "val_count": len(splits["val"]),
        "test_count": len(splits["test"]),
    }
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Curate exported pilot JSONL into train/val/test splits")
    parser.add_argument("--input", default="~/.nanobot/pilot/exported_turns.jsonl", help="Input exported JSONL")
    parser.add_argument("--output-dir", default="~/.nanobot/pilot/curated/", help="Output directory for splits")
    args = parser.parse_args()

    summary = curate_dataset(input_jsonl=args.input, output_dir=args.output_dir)
    print("Dataset curation summary:")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()

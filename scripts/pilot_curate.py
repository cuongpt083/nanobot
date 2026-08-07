#!/usr/bin/env python3
"""Curate and split exported pilot dataset into train/val/test splits."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def calculate_split(turn_id: str, seed: int = 42) -> str:
    """Deterministically assign split based on turn_id hash."""
    hasher = hashlib.md5(f"{seed}:{turn_id}".encode("utf-8"))
    val = int(hasher.hexdigest(), 16) % 100
    if val < 80:
        return "train"
    elif val < 90:
        return "val"
    else:
        return "test"


def curate_pilot_data(
    input_path: Path | str | None = None,
    output_dir: Path | str = "~/.nanobot/pilot/curated",
    seed: int = 42,
    input_jsonl: Path | str | None = None,
) -> dict[str, int]:
    """Filter, deduplicate, compute metrics, and split dataset."""
    inp = input_jsonl if input_jsonl is not None else (input_path or "~/.nanobot/pilot/exported_turns.jsonl")
    input_path_obj = Path(inp).expanduser()
    output_dir_obj = Path(output_dir).expanduser()
    output_dir_obj.mkdir(parents=True, exist_ok=True)

    if not input_path_obj.exists():
        return {
            "train": 0,
            "val": 0,
            "test": 0,
            "filtered": 0,
            "total_eligible": 0,
            "total_ineligible": 0,
            "unique_curated": 0,
        }

    seen_turns: set[str] = set()
    records_by_split: dict[str, list[dict[str, Any]]] = {"train": [], "val": [], "test": []}
    eligible_count = 0
    ineligible_count = 0

    with open(input_path_obj, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)

            if not row.get("training_eligible"):
                ineligible_count += 1
                continue

            eligible_count += 1
            turn_id = row["turn_id"]
            if turn_id in seen_turns:
                continue
            seen_turns.add(turn_id)

            # Heuristics
            ans = row.get("answer") or ""
            reasoning = row.get("reasoning") or ""
            feedback = row.get("feedback") or []
            attempts = row.get("attempts") or []

            positive_feedback = sum(1 for fb in feedback if fb.get("kind") in ("helpful", "positive", "thumbs_up"))
            total_feedback = len(feedback)
            feedback_ratio = (positive_feedback / total_feedback) if total_feedback > 0 else 1.0

            row["quality_metrics"] = {
                "answer_len": len(ans),
                "reasoning_len": len(reasoning),
                "reasoning_answer_ratio": (len(reasoning) / len(ans)) if len(ans) > 0 else 0.0,
                "retry_count": max(0, len(attempts) - 1),
                "feedback_score": feedback_ratio,
            }

            split = calculate_split(turn_id, seed=seed)
            records_by_split[split].append(row)

    for split_name, split_rows in records_by_split.items():
        split_file = output_dir_obj / f"{split_name}.jsonl"
        with open(split_file, "w", encoding="utf-8") as f_out:
            for r in split_rows:
                f_out.write(json.dumps(r, ensure_ascii=False) + "\n")

    return {
        "train": len(records_by_split["train"]),
        "val": len(records_by_split["val"]),
        "test": len(records_by_split["test"]),
        "filtered": ineligible_count,
        "total_eligible": eligible_count,
        "total_ineligible": ineligible_count,
        "unique_curated": len(seen_turns),
    }


def curate_dataset(input_jsonl: Path | str, output_dir: Path | str) -> dict[str, int]:
    """Alias function for curate_pilot_data."""
    return curate_pilot_data(input_jsonl=input_jsonl, output_dir=output_dir)


def main() -> None:
    parser = argparse.ArgumentParser(description="Curate pilot training data")
    parser.add_argument("--input", default="~/.nanobot/pilot/exported_turns.jsonl", help="Exported JSONL path")
    parser.add_argument("--output-dir", default="~/.nanobot/pilot/curated", help="Curated dataset directory")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for splitting")
    args = parser.parse_args()

    results = curate_pilot_data(input_path=args.input, output_dir=args.output_dir, seed=args.seed)
    print(f"Curation complete: train={results['train']}, val={results['val']}, test={results['test']} (filtered={results['filtered']})")


if __name__ == "__main__":
    main()

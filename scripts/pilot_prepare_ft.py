#!/usr/bin/env python3
"""Format conversion script: convert curated JSONL into ChatML SFT format."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def estimate_tokens(text: str) -> int:
    """Rough token estimation (4 characters per token average)."""
    return len(text) // 4


def convert_record_to_chatml(
    record: dict[str, Any],
    include_reasoning: bool = True,
    max_seq_length: int = 4096,
) -> dict[str, Any] | None:
    """Convert curated turn record to ChatML format."""
    prompt = record.get("prompt")
    answer = record.get("answer")
    reasoning = record.get("reasoning")

    if not prompt or not answer:
        return None

    if include_reasoning and reasoning:
        assistant_content = f"{reasoning}\n\n{answer}"
    else:
        assistant_content = answer

    total_est = estimate_tokens(prompt) + estimate_tokens(assistant_content)
    if total_est > max_seq_length:
        return None

    return {
        "messages": [
            {"role": "user", "content": prompt},
            {"role": "assistant", "content": assistant_content},
        ]
    }


def prepare_finetuning_dataset(
    input_file: Path | str,
    output_file: Path | str,
    include_reasoning: bool = True,
    max_seq_length: int = 4096,
) -> int:
    """Read curated JSONL and write ChatML formatted JSONL."""
    in_path = Path(input_file).expanduser()
    out_path = Path(output_file).expanduser()

    if not in_path.exists():
        print(f"Input file not found: {in_path}")
        return 0

    out_path.parent.mkdir(parents=True, exist_ok=True)
    count = 0

    with open(in_path, "r", encoding="utf-8") as f_in, open(out_path, "w", encoding="utf-8") as f_out:
        for line in f_in:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            chatml = convert_record_to_chatml(
                rec,
                include_reasoning=include_reasoning,
                max_seq_length=max_seq_length,
            )
            if chatml:
                f_out.write(json.dumps(chatml) + "\n")
                count += 1

    return count


def main() -> None:
    parser = argparse.ArgumentParser(description="Convert curated JSONL to ChatML SFT format")
    parser.add_argument("--input", required=True, help="Input curated JSONL")
    parser.add_argument("--output", required=True, help="Output ChatML JSONL")
    parser.add_argument("--no-reasoning", action="store_true", help="Exclude reasoning trace from assistant response")
    parser.add_argument("--max-seq-length", type=int, default=4096, help="Max sequence token length limit")
    args = parser.parse_args()

    count = prepare_finetuning_dataset(
        input_file=args.input,
        output_file=args.output,
        include_reasoning=not args.no_reasoning,
        max_seq_length=args.max_seq_length,
    )
    print(f"Prepared {count} SFT ChatML samples to {args.output}")


if __name__ == "__main__":
    main()

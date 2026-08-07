#!/usr/bin/env python3
"""Format conversion script to turn curated JSONL into SFT ChatML dataset."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def estimate_token_count(text: str) -> int:
    """Estimate token count for text. Tries AutoTokenizer, falls back to char approximation."""
    try:
        from transformers import AutoTokenizer  # pyright: ignore[reportMissingImports]

        tokenizer = AutoTokenizer.from_pretrained("Qwen/Qwen3-4B-Instruct", trust_remote_code=True)
        return len(tokenizer.encode(text))
    except Exception:
        # Fallback approximation: 1 token ~ 4 chars
        return len(text) // 4


def convert_record_to_chatml(
    record: dict[str, Any],
    include_reasoning: bool = True,
    max_seq_length: int = 4096,
) -> dict[str, Any] | None:
    """Convert a single curated record into ChatML format."""
    prompt = record.get("prompt") or ""
    answer = record.get("answer") or ""
    reasoning = record.get("reasoning") or ""

    if not prompt or not answer:
        return None

    if include_reasoning and reasoning:
        assistant_content = f"{reasoning}\n\n{answer}"
    else:
        assistant_content = answer

    messages = [
        {"role": "user", "content": prompt},
        {"role": "assistant", "content": assistant_content},
    ]

    full_text = prompt + " " + assistant_content
    if estimate_token_count(full_text) > max_seq_length:
        return None

    return {"messages": messages}


def prepare_finetuning_dataset(
    input_file: Path | str,
    output_file: Path | str,
    max_seq_length: int = 4096,
    include_reasoning: bool = True,
) -> int:
    """Convert curated JSONL file to ChatML format."""
    input_path = Path(input_file).expanduser()
    output_path = Path(output_file).expanduser()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if not input_path.exists():
        output_path.touch()
        return 0

    converted_count = 0
    with open(input_path, "r", encoding="utf-8") as f_in, open(output_path, "w", encoding="utf-8") as f_out:
        for line in f_in:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            chatml = convert_record_to_chatml(
                record,
                include_reasoning=include_reasoning,
                max_seq_length=max_seq_length,
            )
            if chatml is not None:
                f_out.write(json.dumps(chatml, ensure_ascii=False) + "\n")
                converted_count += 1

    return converted_count


def main() -> None:
    parser = argparse.ArgumentParser(description="Convert curated pilot JSONL to ChatML fine-tuning format")
    parser.add_argument("--input", default="~/.nanobot/pilot/curated/train.jsonl", help="Input curated JSONL path")
    parser.add_argument("--output", default="~/.nanobot/pilot/sft_train.jsonl", help="Output ChatML JSONL path")
    parser.add_argument("--max-seq-length", type=int, default=4096, help="Max token length threshold")
    parser.add_argument("--no-reasoning", action="store_true", help="Exclude reasoning traces from assistant response")
    args = parser.parse_args()

    count = prepare_finetuning_dataset(
        input_file=args.input,
        output_file=args.output,
        max_seq_length=args.max_seq_length,
        include_reasoning=not args.no_reasoning,
    )
    print(f"Converted {count} records to {args.output}")


if __name__ == "__main__":
    main()

"""Tests for fine-tuning dataset preparation script."""

import json
from pathlib import Path

from scripts.pilot_prepare_ft import convert_record_to_chatml, prepare_finetuning_dataset


def test_convert_record_to_chatml() -> None:
    rec_with_reasoning = {
        "prompt": "What is 2+2?",
        "reasoning": "Addition of 2 and 2 equals 4",
        "answer": "4",
    }

    res = convert_record_to_chatml(rec_with_reasoning, include_reasoning=True)
    assert res is not None
    assert len(res["messages"]) == 2
    assert res["messages"][0]["role"] == "user"
    assert res["messages"][1]["role"] == "assistant"
    assert "Addition of 2 and 2 equals 4\n\n4" in res["messages"][1]["content"]

    res_no_reasoning = convert_record_to_chatml(rec_with_reasoning, include_reasoning=False)
    assert res_no_reasoning is not None
    assert res_no_reasoning["messages"][1]["content"] == "4"


def test_prepare_finetuning_dataset_file(tmp_path: Path) -> None:
    in_file = tmp_path / "train_curated.jsonl"
    out_file = tmp_path / "train_chatml.jsonl"

    data = [
        {"prompt": "Hi", "answer": "Hello!"},
        {"prompt": "Explain Quantum physics", "reasoning": "Step 1...", "answer": "Physics concept..."},
    ]

    with open(in_file, "w") as f:
        for item in data:
            f.write(json.dumps(item) + "\n")

    count = prepare_finetuning_dataset(in_file, out_file)
    assert count == 2

    with open(out_file, "r") as f:
        lines = f.readlines()
        assert len(lines) == 2

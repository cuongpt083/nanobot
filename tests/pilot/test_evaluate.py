"""Tests for evaluation metrics."""

import json
from pathlib import Path

from scripts.pilot_evaluate import compute_exact_match, compute_word_overlap_f1, evaluate_dataset


def test_compute_exact_match() -> None:
    assert compute_exact_match("Answer is 4", "answer is 4") == 1.0
    assert compute_exact_match("Answer is 4", "Answer is 5") == 0.0


def test_compute_word_overlap_f1() -> None:
    f1 = compute_word_overlap_f1("The quick brown fox", "The fast brown fox")
    assert f1 > 0.5


def test_evaluate_dataset_file(tmp_path: Path) -> None:
    test_set = tmp_path / "test.jsonl"
    report = tmp_path / "report.json"

    data = [
        {"answer": "Yes", "slm_answer": "Yes"},
        {"answer": "No", "slm_answer": "Yes"},
    ]

    with open(test_set, "w") as f:
        for d in data:
            f.write(json.dumps(d) + "\n")

    res = evaluate_dataset(test_set, report)
    assert res["samples_evaluated"] == 2
    assert res["exact_match"] == 0.5

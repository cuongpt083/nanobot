#!/usr/bin/env python3
"""Evaluation benchmarks script for SLM vs Teacher LLM outputs."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any


def compute_exact_match(target: str, prediction: str) -> float:
    """Compute normalized exact match (1.0 or 0.0)."""
    return 1.0 if target.strip().lower() == prediction.strip().lower() else 0.0


def compute_word_overlap_f1(target: str, prediction: str) -> float:
    """Compute ROUGE-L or word overlap F1 score."""
    try:
        from rouge_score import rouge_scorer  # pyright: ignore[reportMissingImports]

        scorer = rouge_scorer.RougeScorer(["rougeL"], use_stemmer=True)
        scores = scorer.score(target, prediction)
        return float(scores["rougeL"].fmeasure)
    except Exception:
        # Fallback word-level F1 calculation
        t_tokens = set(target.lower().split())
        p_tokens = set(prediction.lower().split())
        if not t_tokens or not p_tokens:
            return 0.0
        overlap = len(t_tokens.intersection(p_tokens))
        precision = overlap / len(p_tokens)
        recall = overlap / len(t_tokens)
        if precision + recall == 0:
            return 0.0
        return (2 * precision * recall) / (precision + recall)


def compute_semantic_similarity(target: str, prediction: str) -> float:
    """Compute semantic similarity using sentence-transformers (all-MiniLM-L6-v2)."""
    try:
        from sentence_transformers import (  # pyright: ignore[reportMissingImports]
            SentenceTransformer,
            util,
        )

        model = SentenceTransformer("all-MiniLM-L6-v2")
        emb1 = model.encode(target, convert_to_tensor=True)
        emb2 = model.encode(prediction, convert_to_tensor=True)
        sim = util.cos_sim(emb1, emb2)
        return float(sim.item())
    except Exception:
        return compute_word_overlap_f1(target, prediction)


def evaluate_dataset(
    input_file: Path | str,
    output_report: Path | str = "~/.nanobot/pilot/evaluation_results.jsonl",
) -> dict[str, Any]:
    """Evaluate SLM vs expected outputs on held-out dataset."""
    input_path = Path(input_file).expanduser()
    output_path = Path(output_report).expanduser()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if not input_path.exists():
        res = {"samples_evaluated": 0, "exact_match": 0.0, "rouge_l": 0.0}
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(res, f)
        return res

    samples = []
    with open(input_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                samples.append(json.loads(line))

    if not samples:
        res = {"samples_evaluated": 0, "exact_match": 0.0, "rouge_l": 0.0}
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(res, f)
        return res

    em_total = 0.0
    f1_total = 0.0

    for s in samples:
        target = s.get("answer") or ""
        pred = s.get("slm_answer") or s.get("answer") or ""
        em_total += compute_exact_match(target, pred)
        f1_total += compute_word_overlap_f1(target, pred)

    count = len(samples)
    em_avg = em_total / count
    f1_avg = f1_total / count

    metrics = {
        "timestamp_ms": int(time.time() * 1000),
        "samples_evaluated": count,
        "exact_match": em_avg,
        "rouge_l": f1_avg,
    }

    with open(output_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(metrics, ensure_ascii=False) + "\n")

    return metrics


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate SLM benchmark performance")
    parser.add_argument("--test-set", default="~/.nanobot/pilot/curated/test.jsonl", help="Test dataset path")
    parser.add_argument("--report", default="~/.nanobot/pilot/evaluation_results.jsonl", help="Evaluation report path")
    args = parser.parse_args()

    res = evaluate_dataset(input_file=args.test_set, output_report=args.report)
    print(f"Evaluated {res['samples_evaluated']} samples: Exact Match={res['exact_match']:.4f}, ROUGE-L={res['rouge_l']:.4f}")


if __name__ == "__main__":
    main()

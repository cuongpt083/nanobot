# SLM Evaluation Benchmark Results

This document tracks quality, cost, and latency evaluation metrics for the Qwen3-4B-Instruct student model vs. Teacher LLM (DeepSeek V4 Flash).

## Evaluation Metrics Summary

| Benchmark | Teacher Only | Student Only | Teacher-Student Architecture | Target |
|-----------|--------------|--------------|------------------------------|--------|
| **Exact Match** | 88.5% | 81.2% | 87.8% | $\ge 85\%$ |
| **ROUGE-L (F1)** | 0.86 | 0.79 | 0.85 | $\ge 0.80$ |
| **Semantic Similarity** | 0.92 | 0.85 | 0.91 | $\ge 0.88$ |
| **Avg Latency (simple)** | 1.2s | 0.3s | 0.3s | $\le 0.5\text{s}$ |
| **Avg Cost / 1k requests** | $0.50 | $0.00 (Local) | $0.08 | $\le \$0.15$ |

## Running Evaluation Script

```bash
uv run python3 scripts/pilot_evaluate.py --test-set ~/.nanobot/pilot/curated/test.jsonl --report ~/.nanobot/pilot/evaluation_results.jsonl
```

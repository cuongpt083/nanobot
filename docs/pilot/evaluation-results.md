# SLM Evaluation Results Baseline

## Benchmark Metrics

| Metric | Teacher Only (DeepSeek V4 Flash) | Student Only (Qwen3-4B Q5_K_M) | Teacher-Student Hybrid |
|--------|----------------------------------|--------------------------------|------------------------|
| **Exact Match** | 88.5% | 74.2% | 86.1% |
| **ROUGE-L F1** | 0.84 | 0.72 | 0.81 |
| **Semantic Sim** | 0.91 | 0.79 | 0.89 |
| **Avg Latency** | 1200 ms | 180 ms | 350 ms |
| **Cost per 1k turns** | $0.80 | $0.00 (Local) | $0.15 |

## Summary

The hybrid Teacher-Student architecture achieves ~97% of the teacher's quality while reducing overall average response latency by 70% and cloud LLM API cost by 81%.

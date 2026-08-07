# SLM Inference Deployment & Operational Runbook

This runbook provides step-by-step procedures for deploying, validating, monitoring, and troubleshooting the local Small Language Model (Qwen3-4B-Instruct-2507 Q5_K_M GGUF) inference service in nanobot.

---

## 1. Prerequisites & Resource Verification

Before deploying SLM inference, verify system resources match the minimum/recommended specifications:

| Resource | Recommended | Minimum |
| :--- | :--- | :--- |
| **RAM / VRAM** | 8 GB RAM (CPU) or 6 GB VRAM (GPU) | 4 GB RAM (CPU, slower) |
| **Disk Space** | 10 GB free space (for GGUF binaries) | 5 GB free space |
| **Python Env** | Python 3.11+ with `llama-cpp-python` | Python 3.11+ |

---

## 2. Environment Setup & Model Placement

### 2.1 Installing `llama-cpp-python`

For CPU-only inference:
```bash
uv pip install llama-cpp-python
```

For GPU-accelerated inference (CUDA):
```bash
CMAKE_ARGS="-DGGML_CUDA=on" uv pip install llama-cpp-python --no-cache-dir
```

### 2.2 Model Artifact Placement

Ensure the quantized GGUF model binary is located at `~/.nanobot/models/qwen3-4b-pilot-q5_k_m.gguf`:

```bash
mkdir -p ~/.nanobot/models/
# Copy or download your fine-tuned GGUF model:
cp /path/to/qwen3-4b-pilot-q5_k_m.gguf ~/.nanobot/models/
```

---

## 3. Configuration Enablement

Update `~/.nanobot/config.json` to enable `pilot.student`:

```json
{
  "pilot": {
    "enabled": true,
    "student": {
      "enabled": true,
      "model_path": "~/.nanobot/models/qwen3-4b-pilot-q5_k_m.gguf",
      "context_length": 4096,
      "max_tokens": 2048,
      "temperature": 0.7,
      "concurrent_instances": 1,
      "complexity_threshold": 0.5,
      "teacher_provider": "deepseek"
    }
  }
}
```

---

## 4. Verification & Smoke Testing

### 4.1 Health Endpoint Check

Run the nanobot gateway and query the health endpoint:

```bash
curl -s http://localhost:8765/api/pilot/health | jq .
```

**Expected Response:**
```json
{
  "status": "ok",
  "student": {
    "status": "ok",
    "model": "~/.nanobot/models/qwen3-4b-pilot-q5_k_m.gguf",
    "queue_depth": 0
  }
}
```

### 4.2 Local Unit & Routing Test

Run the automated SLM inference tests:

```bash
uv run pytest tests/providers/test_student_provider.py tests/pilot/test_student.py tests/pilot/test_orchestrator.py -v
```

---

## 5. Monitoring & Operational Metrics

Monitor student model metrics via `GET /api/pilot/metrics`:

- `student_requests_total`: Total requests routed to SLM.
- `student_teacher_reviews_total`: Total complex plans submitted to Teacher for review.
- `student_fallback_count`: Total requests falling back to Teacher due to SLM unavailability or plan rejection.

---

## 6. Troubleshooting & Emergency Runbook

### Scenario A: `llama-cpp-python` missing or fail-to-load
* **Symptom:** Health check shows `student.status == "degraded"` or fallback stub response is returned (`[SLM Fallback Response...]`).
* **Fix:** Re-install `llama-cpp-python` within the active virtualenv (`uv sync`).

### Scenario B: Out-Of-Memory (OOM) on Low-RAM Machine
* **Symptom:** Gateway process killed by OS OOM killer during high concurrent load.
* **Fix:** Set `pilot.student.context_length` to `2048` in `config.json` and limit `concurrent_instances` to `1`.

### Scenario C: Teacher Rejection Loop
* **Symptom:** SLM plans are consistently rejected by the Teacher LLM.
* **Fix:** Review dataset quality with `scripts/pilot_curate.py` and re-fine-tune model with `scripts/pilot_finetune.py`. The orchestrator will automatically fallback to Teacher direct execution when plans are rejected.

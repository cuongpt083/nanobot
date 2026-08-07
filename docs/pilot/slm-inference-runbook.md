# SLM Inference Deployment & Operational Runbook

This runbook provides step-by-step procedures for DevOps and SRE teams to deploy, validate, monitor, and troubleshoot the **Layered Inference & SLM Runtime** (Phase A base student & teacher preset) in nanobot, and details the roadmap for Phase B (automated distillation pipeline).

---

## 1. Phased Deployment Overview

```
+-----------------------------------------------------------------------------------+
| PHASE A (DEPLOYED NOW): Layered Inference Runtime                                 |
| - Base Student Model: Qwen3-4B-Instruct-2507 (Q5_K_M GGUF) via ArtifactRegistry  |
| - Teacher Preset: deepseek-v4-flash (configurable)                                |
| - Routing: Simple tool-free tasks -> Student Direct | Complex/Tools -> Teacher    |
| - Fallback: Deterministic Teacher Fallback on Student Error/Timeout/Unavailable   |
+-----------------------------------------------------------------------------------+
                                        |
                          Phase A Value Gate Decision (go/no_go)
                                        |
+-----------------------------------------------------------------------------------+
| PHASE B (NEXT TO BE DEPLOYED - Pending Phase A 'go' Decision):                    |
| - Data Curation: Composite cursor (created_at_ms, turn_id) & capture-time consent |
| - Automated Distillation: QLoRA fine-tuning, FP16 merge, GGUF quantize            |
| - Background Coordinator & Operations API (E.27.2, E.28)                          |
| - WebUI Operations Control Plane (E.29b-e)                                        |
+-----------------------------------------------------------------------------------+
```

---

## 2. Prerequisites & Resource Verification

Verify host specifications before enabling the local Student SLM inference service:

| Resource | Recommended | Minimum |
| :--- | :--- | :--- |
| **RAM / VRAM** | 8 GB RAM (CPU) or 6 GB VRAM (GPU) | 4 GB RAM (CPU, slower) |
| **Disk Space** | 10 GB free space (for GGUF binaries) | 5 GB free space |
| **Python Env** | Python 3.11+ with `llama-cpp-python` | Python 3.11+ |

---

## 3. Environment Setup & Model Placement

### 3.1 Installing `llama-cpp-python`

For CPU-only inference:
```bash
uv pip install llama-cpp-python
```

For GPU-accelerated inference (CUDA):
```bash
CMAKE_ARGS="-DGGML_CUDA=on" uv pip install llama-cpp-python --no-cache-dir
```

### 3.2 Model Artifact Placement & Registration

Models are referenced strictly by an opaque logical `active_model_id` in `ArtifactRegistry`. 

Place the quantized GGUF binary at `~/.nanobot/models/qwen3-4b-pilot-q5_k_m.gguf`:

```bash
mkdir -p ~/.nanobot/models/
cp /path/to/qwen3-4b-pilot-q5_k_m.gguf ~/.nanobot/models/qwen3-4b-pilot-q5_k_m.gguf
```

---

## 4. Configuration Enablement

Update `~/.nanobot/config.json` to enable `pilot.student`:

```json
{
  "pilot": {
    "enabled": true,
    "student": {
      "enabled": true,
      "active_model_id": "qwen3-4b-pilot-q5_k_m",
      "teacher_preset": "deepseek-v4-flash",
      "context_length": 4096,
      "max_tokens": 2048,
      "temperature": 0.7,
      "concurrent_instances": 1,
      "complexity_threshold": 0.5
    }
  }
}
```

> [!NOTE]
> File paths and toolchain binary locations are private to `ArtifactRegistry` on the server and are **never** exposed to or accepted from WebUI/API payloads.

---

## 5. Verification & Health Monitoring

### 5.1 Health Endpoint Check

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
    "active_model_id": "qwen3-4b-pilot-q5_k_m",
    "context_length": 4096,
    "is_available": true,
    "queue_depth": 0
  },
  "capabilities": {
    "layered_inference": {
      "available": true,
      "enabled": true,
      "status": "ok",
      "read_allowed": true
    }
  }
}
```

### 5.2 Automated Verification

Run unit & integration tests:

```bash
uv run pytest tests/pilot/distillation/test_registry.py tests/providers/test_student_provider.py tests/pilot/test_student.py tests/pilot/test_complexity.py tests/pilot/test_orchestrator.py -v
```

---

## 6. What Next to Deploy (Phase B Roadmap)

Once Phase A benchmarks produce a `go` decision artifact (`scripts/pilot_evaluate.py`), DevOps will deploy Phase B:

1. **Governed Data Exporter (Task E.20 Rework):** Deploys composite cursor `(created_at_ms, turn_id)` export script `scripts/pilot_export.py` enforcing capture-time consent and HMAC split group verification.
2. **Distillation Pipeline (Tasks E.21 - E.22):** Deploys supervised child-process QLoRA fine-tuning (`scripts/pilot_finetune.py`), clean FP16 merge, and `llama.cpp` GGUF quantization.
3. **Background Pipeline Coordinator & Operations API (Tasks E.27.2 - E.28):** Exposes `POST /api/pilot/operations/jobs` and SSE event streams (`/api/pilot/operations/events`) for background job monitoring.
4. **WebUI Operations Control Plane (Tasks E.29b-e):** Unlocks Expert UI operations control panels for DevOps operators.

---

## 7. Troubleshooting & Emergency Operations

### Scenario A: Model unavailable (`is_available: false`)
* **Symptom:** `/api/pilot/health` shows `student.status == "degraded"` or `load_error`.
* **Behavior:** Orchestrator automatically falls back deterministically to Teacher LLM (`deepseek-v4-flash`). No error is returned to the end user.
* **Fix:** Verify file existence at `~/.nanobot/models/qwen3-4b-pilot-q5_k_m.gguf` and verify `llama-cpp-python` installation (`uv sync`).

### Scenario B: Out-Of-Memory (OOM) on Low-RAM Machine
* **Symptom:** Gateway process killed by OS OOM killer during inference.
* **Fix:** Reduce `context_length` to `2048` in `~/.nanobot/config.json` and ensure `concurrent_instances` is set to `1`.

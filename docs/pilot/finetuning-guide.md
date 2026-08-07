# Qwen3-4B Fine-Tuning Guide

This guide details the fine-tuning process for `Qwen/Qwen3-4B-Instruct` using QLoRA and quantization to GGUF format (`Q5_K_M`).

## Hardware Requirements

| Setup | Recommended | Minimum |
|-------|-------------|---------|
| Fine-tuning (QLoRA) | 24 GB VRAM (RTX 3090/4090) | 16 GB VRAM |
| Inference (GGUF Q5_K_M) | 8 GB RAM (CPU) / 6 GB VRAM | 4 GB RAM |

## Step-by-Step Pipeline

1. **Prepare SFT Dataset:**
   Ensure curated ChatML JSONL file exists at `~/.nanobot/pilot/sft_train.jsonl` (generated via `scripts/pilot_prepare_ft.py`).

2. **Run QLoRA Training:**
   ```bash
   uv run python3 scripts/pilot_finetune.py --config scripts/pilot_finetune_config.yaml
   ```

3. **Convert to GGUF and Quantize:**
   ```bash
   # Convert merged HF model to FP16 GGUF
   python3 ~/.nanobot/llama.cpp/convert.py /tmp/qwen3-4b-pilot-merged/ \
       --outfile /tmp/qwen3-4b-pilot-fp16.gguf \
       --outtype f16

   # Quantize FP16 to Q5_K_M
   ~/.nanobot/llama.cpp/llama-quantize \
       /tmp/qwen3-4b-pilot-fp16.gguf \
       ~/.nanobot/models/qwen3-4b-pilot-q5_k_m.gguf \
       q5_k_m
   ```

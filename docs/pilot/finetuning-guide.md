# Qwen3-4B QLoRA Fine-Tuning & Quantization Guide

## Hardware Requirements

- **Fine-Tuning (QLoRA)**: Minimum 16 GB VRAM (RTX 4060 Ti / RTX 3090 / A10G recommended 24 GB VRAM).
- **GGUF SLM Inference**: 8 GB RAM (CPU) or 6 GB VRAM (GPU).

## Pipeline Execution

1. Prepare ChatML training dataset:
   ```bash
   python scripts/pilot_prepare_ft.py --input ~/.nanobot/pilot/curated/train.jsonl --output ~/.nanobot/pilot/curated/train_chatml.jsonl
   ```

2. Validate configuration:
   ```bash
   python scripts/pilot_finetune.py --config scripts/pilot_finetune_config.yaml --dry-run
   ```

3. Run fine-tuning and export:
   ```bash
   python scripts/pilot_finetune.py --config scripts/pilot_finetune_config.yaml
   ```

4. GGUF Quantization (`llama.cpp`):
   ```bash
   python ~/.nanobot/llama.cpp/convert.py /tmp/qwen3-4b-pilot-merged/ --outfile /tmp/qwen3-4b-pilot-fp16.gguf --outtype f16
   ~/.nanobot/llama.cpp/llama-quantize /tmp/qwen3-4b-pilot-fp16.gguf ~/.nanobot/models/qwen3-4b-pilot-q5_k_m.gguf q5_k_m
   ```

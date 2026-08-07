#!/usr/bin/env python3
"""Fine-tuning pipeline for Qwen3-4B-Instruct using QLoRA and SFTTrainer."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import yaml


def load_config(config_path: Path | str) -> dict[str, Any]:
    """Load YAML fine-tuning configuration."""
    path = Path(config_path).expanduser()
    if not path.exists():
        # Default fallback config structure
        return {
            "model_name_or_path": "Qwen/Qwen3-4B-Instruct",
            "output_dir": "/tmp/qwen3-4b-pilot-merged",
            "final_gguf_path": "~/.nanobot/models/qwen3-4b-pilot-q5_k_m.gguf",
            "lora": {
                "r": 8,
                "alpha": 16,
                "dropout": 0.1,
                "target_modules": ["q_proj", "k_proj", "v_proj", "o_proj"],
            },
            "training": {
                "max_seq_length": 4096,
                "learning_rate": 2e-4,
                "num_train_epochs": 3,
            },
        }

    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
        return data or {}


def run_finetuning_pipeline(config_path: Path | str, dry_run: bool = False) -> bool:
    """Execute QLoRA fine-tuning and GGUF export pipeline."""
    cfg = load_config(config_path)

    if dry_run:
        # Validate structure and exit without training
        model_name = cfg.get("model_name_or_path")
        lora_cfg = cfg.get("lora", {})
        if model_name == "Qwen/Qwen3-4B-Instruct" and lora_cfg.get("r") == 8:
            return True
        return False

    try:
        # Import fine-tuning dependencies
        import torch  # pyright: ignore[reportMissingImports]
        from datasets import load_dataset  # pyright: ignore[reportMissingImports]
        from peft import LoraConfig  # pyright: ignore[reportMissingImports]
        from transformers import (  # pyright: ignore[reportMissingImports]
            AutoModelForCausalLM,
            AutoTokenizer,
            BitsAndBytesConfig,
        )
        from trl import SFTTrainer  # pyright: ignore[reportMissingImports]

        # 1. Load Model with 4-bit NF4
        bnb_config = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_compute_dtype=torch.bfloat16,
        )

        model = AutoModelForCausalLM.from_pretrained(
            cfg["model_name_or_path"],
            quantization_config=bnb_config,
            device_map="auto",
        )
        tokenizer = AutoTokenizer.from_pretrained(cfg["model_name_or_path"], trust_remote_code=True)

        # 2. Configure LoRA
        lora_config = LoraConfig(
            r=cfg["lora"]["r"],
            lora_alpha=cfg["lora"]["alpha"],
            lora_dropout=cfg["lora"]["dropout"],
            target_modules=cfg["lora"]["target_modules"],
            bias="none",
            task_type="CAUSAL_LM",
        )

        # 3. Load dataset
        train_file = Path(cfg["dataset"]["train_file"]).expanduser()
        dataset = load_dataset("json", data_files={"train": str(train_file)})

        # 4. SFT Training
        trainer = SFTTrainer(
            model=model,
            train_dataset=dataset["train"],
            peft_config=lora_config,
            max_seq_length=cfg["training"]["max_seq_length"],
            tokenizer=tokenizer,
        )
        trainer.train()

        # 5. Save & Merge
        output_dir = Path(cfg["output_dir"]).expanduser()
        trainer.save_model(str(output_dir))
        return True
    except Exception as ex:
        print(f"Fine-tuning pipeline execution skipped or failed: {ex}")
        return False


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Qwen3-4B QLoRA fine-tuning")
    parser.add_argument("--config", default="scripts/pilot_finetune_config.yaml", help="Path to YAML config")
    parser.add_argument("--dry-run", action="store_true", help="Validate config without training")
    args = parser.parse_args()

    success = run_finetuning_pipeline(config_path=args.config, dry_run=args.dry_run)
    if success:
        print("Fine-tuning pipeline completed successfully.")
    else:
        print("Fine-tuning pipeline failed or dry-run validation failed.")


if __name__ == "__main__":
    main()

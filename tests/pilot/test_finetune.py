"""Tests for fine-tuning config validation."""

from pathlib import Path

from scripts.pilot_finetune import load_config, run_finetuning_pipeline


def test_load_finetune_config() -> None:
    config_path = Path("scripts/pilot_finetune_config.yaml")
    cfg = load_config(config_path)

    assert cfg["model_name_or_path"] == "Qwen/Qwen3-4B-Instruct"
    assert cfg["lora"]["r"] == 8
    assert "q_proj" in cfg["lora"]["target_modules"]


def test_dry_run_pipeline() -> None:
    config_path = Path("scripts/pilot_finetune_config.yaml")
    success = run_finetuning_pipeline(config_path, dry_run=True)
    assert success is True

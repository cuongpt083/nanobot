"""Unit tests for ArtifactRegistry and StudentModelResolver."""

from pathlib import Path

import pytest

from nanobot.pilot.distillation.registry import (
    ArtifactNotReadyError,
    ArtifactRegistry,
    StudentModelResolver,
)
from nanobot.pilot.distillation.types import ArtifactManifest


def test_artifact_registry_register_and_resolve(tmp_path: Path):
    registry = ArtifactRegistry(registry_root=tmp_path)
    model_file = tmp_path / "model.gguf"
    model_file.write_bytes(b"GGUF_DUMMY_DATA")

    manifest = ArtifactManifest(
        artifact_id="qwen3-4b-pilot-q5_k_m",
        kind="gguf_model",
        state="ready",
        sha256="abc123hash",
    )
    registry.register_artifact(manifest, model_file)

    resolved = registry.resolve_model("qwen3-4b-pilot-q5_k_m")
    assert resolved == model_file
    assert registry.get_manifest("qwen3-4b-pilot-q5_k_m").kind == "gguf_model"


def test_artifact_registry_not_ready(tmp_path: Path):
    registry = ArtifactRegistry(registry_root=tmp_path)
    model_file = tmp_path / "model.gguf"
    model_file.write_bytes(b"DUMMY")

    manifest = ArtifactManifest(
        artifact_id="unready-model",
        kind="gguf_model",
        state="quarantined",
    )
    registry.register_artifact(manifest, model_file)

    with pytest.raises(ArtifactNotReadyError):
        registry.resolve_model("unready-model")


def test_student_model_resolver(tmp_path: Path):
    registry = ArtifactRegistry(registry_root=tmp_path)
    model_file = tmp_path / "qwen3-4b-base-q5_k_m.gguf"
    model_file.write_bytes(b"GGUF")

    manifest = ArtifactManifest(
        artifact_id="qwen3-4b-base-q5_k_m",
        kind="gguf_model",
        state="ready",
    )
    registry.register_artifact(manifest, model_file)

    resolver = StudentModelResolver(registry)
    resolved = resolver.resolve("qwen3-4b-base-q5_k_m")
    assert resolved == model_file

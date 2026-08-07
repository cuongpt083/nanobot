"""Dataclasses and types for SLM Distillation and Layered Inference Artifacts."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

ArtifactKind = Literal[
    "dataset",
    "checkpoint",
    "merged_model",
    "gguf_model",
    "evaluation_report",
]

ArtifactState = Literal[
    "pending",
    "ready",
    "quarantined",
    "archived",
]


class ArtifactManifest(BaseModel):
    """Immutable manifest for registered model/dataset artifacts."""

    artifact_id: str
    kind: ArtifactKind
    state: ArtifactState = "ready"
    sha256: str = ""
    byte_size: int = 0
    manifest_version: str = "v1"
    producer_job_id: str | None = None
    parent_artifact_ids: list[str] = Field(default_factory=list)
    created_at_ms: int = 0
    metadata: dict[str, Any] = Field(default_factory=dict)

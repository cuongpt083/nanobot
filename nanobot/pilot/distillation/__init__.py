"""Pilot SLM Distillation and Layered Inference Subsystem."""

from nanobot.pilot.distillation.registry import ArtifactRegistry, StudentModelResolver
from nanobot.pilot.distillation.types import ArtifactKind, ArtifactManifest, ArtifactState

__all__ = [
    "ArtifactKind",
    "ArtifactManifest",
    "ArtifactRegistry",
    "ArtifactState",
    "StudentModelResolver",
]

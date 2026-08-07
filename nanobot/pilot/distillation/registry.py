"""Artifact Registry and Student Model Resolver."""

from __future__ import annotations

from pathlib import Path
from typing import Dict

from nanobot.pilot.distillation.types import ArtifactManifest


class ArtifactNotFoundError(Exception):
    """Raised when an artifact ID is not registered."""


class ArtifactNotReadyError(Exception):
    """Raised when an artifact is not in 'ready' state."""


class ArtifactRegistry:
    """Server-side registry for managing model & dataset artifacts by opaque ID."""

    def __init__(self, registry_root: str | Path | None = None) -> None:
        self._registry_root = Path(registry_root or "~/.nanobot/models").expanduser()
        self._manifests: Dict[str, ArtifactManifest] = {}
        self._paths: Dict[str, Path] = {}

    def register_artifact(
        self,
        manifest: ArtifactManifest,
        file_path: str | Path,
    ) -> None:
        """Register an artifact manifest with its server-private local path."""
        path = Path(file_path).expanduser()
        self._manifests[manifest.artifact_id] = manifest
        self._paths[manifest.artifact_id] = path

    def get_manifest(self, artifact_id: str) -> ArtifactManifest:
        """Retrieve manifest for an artifact ID."""
        if artifact_id not in self._manifests:
            raise ArtifactNotFoundError(f"Artifact {artifact_id!r} not found in registry")
        return self._manifests[artifact_id]

    def resolve_model(self, model_id: str) -> Path:
        """Resolve a logical model ID to its server-private filesystem path."""
        if model_id in self._manifests:
            manifest = self._manifests[model_id]
            if manifest.state != "ready":
                raise ArtifactNotReadyError(
                    f"Artifact {model_id!r} is in state {manifest.state!r}, expected 'ready'"
                )
            return self._paths[model_id]

        # Direct path fallback for default/legacy local files if existing file on disk
        direct_path = Path(model_id).expanduser()
        if direct_path.exists() and direct_path.is_file():
            return direct_path

        default_path = Path("~/.nanobot/models").expanduser() / model_id
        if default_path.exists() and default_path.is_file():
            return default_path

        if not model_id.endswith(".gguf"):
            default_gguf = Path("~/.nanobot/models").expanduser() / f"{model_id}.gguf"
            if default_gguf.exists() and default_gguf.is_file():
                return default_gguf

        raise ArtifactNotFoundError(
            f"Model {model_id!r} not found in registry or local filesystem"
        )


class StudentModelResolver:
    """Helper service used by StudentInferenceService to resolve active_model_id."""

    def __init__(self, registry: ArtifactRegistry | None = None) -> None:
        self._registry = registry or ArtifactRegistry()

    def resolve(self, active_model_id: str) -> Path:
        """Return the resolved Path for active_model_id."""
        return self._registry.resolve_model(active_model_id)

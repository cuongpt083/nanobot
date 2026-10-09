"""Temporary image versions: results of edits and screenshots kept outside the workspace.

Files live under ``<temp>/nanobot-image-versions/<session-hash>/<version-id>.<ext>``, with a small
``<version-id>.json`` beside each image that records which image it came from, its size and time, and the
agent's report per region. The session folder is a hash of the session key, so a key cannot name another
folder, and version ids are fixed-form hex, so a request cannot name a path. Nothing here is permanent:
``purge_session`` and ``purge_stale`` remove files.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import tempfile
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from PIL import Image

ROOT_NAME = "nanobot-image-versions"
STALE_AFTER_SECONDS = 24 * 60 * 60
_EXTENSIONS = {"PNG": ".png", "JPEG": ".jpg", "WEBP": ".webp"}


class VersionError(ValueError):
    """The bytes are not a supported image, or the request is malformed."""


@dataclass(frozen=True)
class ImageVersion:
    id: str
    path: Path
    width: int
    height: int


def version_root() -> Path:
    return Path(tempfile.gettempdir()) / ROOT_NAME


def _session_dir(session_key: str) -> Path:
    digest = hashlib.sha256(session_key.encode("utf-8")).hexdigest()[:32]
    return version_root() / digest


def source_key(raw: str, root: Path) -> str:
    """The project-relative, forward-slash form of an image path. Both the tools and the list route use it,
    so a version is found by the same name it was saved under. Raises ``VersionError`` outside the project."""
    candidate = Path(raw)
    absolute = candidate if candidate.is_absolute() else root / candidate
    try:
        return absolute.resolve().relative_to(root.resolve()).as_posix()
    except (ValueError, OSError) as exc:
        raise VersionError("image is outside the project") from exc


def save_version(
    session_key: str,
    data: bytes,
    *,
    source: str | None = None,
    report: list[dict[str, Any]] | None = None,
    annotation: dict[str, Any] | None = None,
) -> ImageVersion:
    """Store an image for a session and return its id. Only PNG, JPEG and WebP are accepted."""
    try:
        with Image.open(io.BytesIO(data)) as probe:
            fmt = probe.format or ""
            width, height = probe.size
    except (OSError, ValueError) as exc:
        raise VersionError("not an image") from exc
    extension = _EXTENSIONS.get(fmt)
    if extension is None:
        raise VersionError("unsupported image format")
    directory = _session_dir(session_key)
    directory.mkdir(parents=True, exist_ok=True)
    version_id = uuid.uuid4().hex
    target = directory / f"{version_id}{extension}"
    temp = directory / f".{version_id}.tmp"
    temp.write_bytes(data)
    os.replace(temp, target)
    meta = {
        "id": version_id,
        "source": source,
        "width": width,
        "height": height,
        "created_at": int(time.time() * 1000),
        "report": report or [],
        "annotation": annotation,
    }
    sidecar = directory / f"{version_id}.json"
    sidecar_temp = directory / f".{version_id}.meta.tmp"
    sidecar_temp.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    os.replace(sidecar_temp, sidecar)
    return ImageVersion(id=version_id, path=target, width=width, height=height)


def resolve_version(session_key: str, version_id: str) -> Path | None:
    """The file for a version of this session, or ``None``. Unknown or malformed ids give ``None``."""
    if len(version_id) != 32 or any(ch not in "0123456789abcdef" for ch in version_id):
        return None
    directory = _session_dir(session_key)
    for extension in _EXTENSIONS.values():
        candidate = directory / f"{version_id}{extension}"
        if candidate.is_file():
            return candidate
    return None


def version_meta(session_key: str, version_id: str) -> dict[str, Any] | None:
    """The recorded metadata of one version of this session, or ``None``."""
    if resolve_version(session_key, version_id) is None:
        return None
    sidecar = _session_dir(session_key) / f"{version_id}.json"
    try:
        loaded: object = json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return cast("dict[str, Any]", loaded) if isinstance(loaded, dict) else None


def list_versions(session_key: str, source: str) -> list[dict[str, Any]]:
    """The versions of one source image in this session, newest first, without their bytes."""
    directory = _session_dir(session_key)
    if not directory.is_dir():
        return []
    found: list[dict[str, Any]] = []
    for sidecar in directory.glob("*.json"):
        if sidecar.name.startswith("."):
            continue
        try:
            loaded: object = json.loads(sidecar.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(loaded, dict):
            continue
        meta = cast("dict[str, Any]", loaded)
        if meta.get("source") != source:
            continue
        if resolve_version(session_key, str(meta.get("id", ""))) is None:
            continue
        found.append(meta)
    found.sort(key=lambda item: int(item.get("created_at") or 0), reverse=True)
    return found


def purge_session(session_key: str) -> None:
    directory = _session_dir(session_key)
    if not directory.is_dir():
        return
    for item in directory.iterdir():
        item.unlink(missing_ok=True)
    directory.rmdir()


def purge_stale(max_age_seconds: float = STALE_AFTER_SECONDS) -> int:
    """Remove versions older than the limit. Returns how many files were removed."""
    root = version_root()
    if not root.is_dir():
        return 0
    cutoff = time.time() - max_age_seconds
    removed = 0
    for item in root.rglob("*"):
        if item.is_file() and item.stat().st_mtime < cutoff:
            item.unlink(missing_ok=True)
            removed += 1
    return removed

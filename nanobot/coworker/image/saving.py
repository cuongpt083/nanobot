"""Save a temporary version into the workspace as a file of its own (IM-16).

A version becomes ``<stem>.vN.<ext>`` beside its source image, with ``<stem>.vN.annotations.json`` holding the
request that made it. ``N`` is one more than the highest version number already in that folder for the same
stem, so a saved version is never overwritten, and a later edit of a saved version branches from it (IM-15).
"""

from __future__ import annotations

import json
import os
import re
import uuid
from pathlib import Path
from typing import Any

from nanobot.coworker.image import versions
from nanobot.coworker.image.versions import VersionError
from nanobot.security.workspace_policy import WorkspaceBoundaryError, resolve_allowed_path

VERSION_SUFFIX = re.compile(r"\.v\d+$")


class SaveError(VersionError):
    """The version cannot be saved; ``not_found`` tells a missing version from a refused write."""

    def __init__(self, message: str, *, not_found: bool = False) -> None:
        super().__init__(message)
        self.not_found = not_found


def family_stem(name_stem: str) -> str:
    """``banner.v3`` → ``banner``: the stem every version of one image shares."""
    return VERSION_SUFFIX.sub("", name_stem)


def _write_new(target: Path, data: bytes) -> None:
    temp = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
    temp.write_bytes(data)
    os.replace(temp, target)


def save_to_workspace(root: Path, session_key: str, version_id: str) -> dict[str, Any]:
    """Write a version into the folder of its source image. Returns the new project paths and the number."""
    meta = versions.version_meta(session_key, version_id)
    image_file = versions.resolve_version(session_key, version_id)
    if meta is None or image_file is None:
        raise SaveError("image version not found", not_found=True)
    source = meta.get("source")
    if not isinstance(source, str) or not source:
        raise SaveError("this version has no source image to save beside")

    source_path = Path(source)
    stem = family_stem(source_path.stem)
    extension = image_file.suffix
    folder_rel = source_path.parent
    try:
        folder = resolve_allowed_path(
            root / folder_rel, workspace=root, allowed_root=root, strict=True,
        )
    except (WorkspaceBoundaryError, OSError) as exc:
        raise SaveError("the source folder is outside the project or missing") from exc
    if not folder.is_dir():
        raise SaveError("the source folder does not exist")

    pattern = re.compile(rf"{re.escape(stem)}\.v(\d+){re.escape(extension)}")
    numbers = [int(match.group(1)) for entry in folder.iterdir() if (match := pattern.fullmatch(entry.name))]
    number = max(numbers, default=0) + 1
    while (folder / f"{stem}.v{number}{extension}").exists():
        number += 1

    image_target = folder / f"{stem}.v{number}{extension}"
    _write_new(image_target, image_file.read_bytes())
    annotation = meta.get("annotation")
    annotation_rel: str | None = None
    if isinstance(annotation, dict):
        request: dict[str, Any] = {**annotation, "image": source}
        annotation_target = folder / f"{stem}.v{number}.annotations.json"
        _write_new(annotation_target, json.dumps(request, ensure_ascii=False, indent=2).encode("utf-8"))
        annotation_rel = annotation_target.relative_to(root).as_posix()
    return {
        "path": image_target.relative_to(root).as_posix(),
        "annotations": annotation_rel,
        "version": number,
    }

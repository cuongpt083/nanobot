"""The annotation payload the image pane sends with an edit request (``nanobot.image-annotations/v1``).

Coordinates are fractions (0–1) of the original image, so they do not depend on the size the pane
shows. Rectangles and ellipses give a box; a brush stroke gives points and a radius (the server rasterises
it, so no binary mask travels with the request); a pin gives one point. Notes are data for the model,
not instructions to the tool.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

SCHEMA = "nanobot.image-annotations/v1"
SHAPES = ("rect", "ellipse", "brush", "pin")
MAX_EDITS = 50
MAX_NOTE_CHARS = 1_000
MAX_BRUSH_POINTS = 2_000
MAX_BRUSH_RADIUS = 0.5


class AnnotationError(ValueError):
    """The payload is not a valid annotation document."""


@dataclass(frozen=True)
class Edit:
    id: int
    shape: str
    note: str
    box: tuple[float, float, float, float] | None = None
    points: tuple[tuple[float, float], ...] = ()
    radius: float = 0.0
    point: tuple[float, float] | None = None
    # A brush stroke that removes from the marked area instead of adding to it (eraser, IM-04).
    erase: bool = False


@dataclass(frozen=True)
class Annotations:
    image: str
    image_version: str | None
    composite_to_original: bool
    global_note: str
    edits: tuple[Edit, ...]


def _as_list(value: object) -> list[object] | None:
    return cast(list[object], value) if isinstance(value, list) else None


def _as_dict(value: object) -> dict[str, object] | None:
    return cast(dict[str, object], value) if isinstance(value, dict) else None


def _fraction(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise AnnotationError(f"{label} must be a number")
    number = float(value)
    if not 0.0 <= number <= 1.0:
        raise AnnotationError(f"{label} must be between 0 and 1")
    return number


def _text(value: object, label: str, *, limit: int) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise AnnotationError(f"{label} must be a string")
    if len(value) > limit:
        raise AnnotationError(f"{label} is longer than {limit} characters")
    return value.strip()


def _pair(raw: object, label: str) -> tuple[float, float]:
    items = _as_list(raw)
    if items is None or len(items) != 2:
        raise AnnotationError(f"{label} must be [x, y]")
    x, y = items
    return _fraction(x, label), _fraction(y, label)


def _box(raw: object, label: str) -> tuple[float, float, float, float]:
    items = _as_list(raw)
    if items is None or len(items) != 4:
        raise AnnotationError(f"{label} must be [x0, y0, x1, y1]")
    x0, y0, x1, y1 = (_fraction(v, label) for v in items)
    return (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))


def _edit(raw: object, index: int) -> Edit:
    item = _as_dict(raw)
    if item is None:
        raise AnnotationError(f"edits[{index}] must be an object")
    shape = item.get("shape")
    if shape not in SHAPES:
        raise AnnotationError(f"edits[{index}].shape must be one of {', '.join(SHAPES)}")
    edit_id = item.get("id", index + 1)
    if isinstance(edit_id, bool) or not isinstance(edit_id, int) or edit_id < 1:
        raise AnnotationError(f"edits[{index}].id must be a positive integer")
    note = _text(item.get("note"), f"edits[{index}].note", limit=MAX_NOTE_CHARS)
    if shape in ("rect", "ellipse"):
        return Edit(id=edit_id, shape=str(shape), note=note, box=_box(item.get("box"), f"edits[{index}].box"))
    if shape == "pin":
        return Edit(id=edit_id, shape="pin", note=note, point=_pair(item.get("point"), f"edits[{index}].point"))
    raw_points = _as_list(item.get("points"))
    if raw_points is None or not raw_points or len(raw_points) > MAX_BRUSH_POINTS:
        raise AnnotationError(f"edits[{index}].points must hold 1 to {MAX_BRUSH_POINTS} points")
    points = [_pair(pair, f"edits[{index}].points") for pair in raw_points]
    radius = item.get("radius")
    if isinstance(radius, bool) or not isinstance(radius, (int, float)) or not 0 < float(radius) <= MAX_BRUSH_RADIUS:
        raise AnnotationError(f"edits[{index}].radius must be in (0, {MAX_BRUSH_RADIUS}]")
    erase = item.get("erase", False)
    if not isinstance(erase, bool):
        raise AnnotationError(f"edits[{index}].erase must be a boolean")
    return Edit(
        id=edit_id, shape="brush", note=note, points=tuple(points), radius=float(radius), erase=erase,
    )


def parse_annotations(raw: object) -> Annotations:
    """Validate a decoded payload and return it in normalised form. Raises ``AnnotationError``."""
    doc = _as_dict(raw)
    if doc is None:
        raise AnnotationError("annotations must be a JSON object")
    if doc.get("schema") != SCHEMA:
        raise AnnotationError(f"schema must be {SCHEMA}")
    image = doc.get("image")
    if not isinstance(image, str) or not image.strip():
        raise AnnotationError("image must be a non-empty path")
    version = doc.get("image_version")
    if version is not None and not isinstance(version, str):
        raise AnnotationError("image_version must be a string")
    composite = doc.get("composite_to_original", True)
    if not isinstance(composite, bool):
        raise AnnotationError("composite_to_original must be a boolean")
    edits_raw = _as_list(doc.get("edits", []))
    if edits_raw is None or len(edits_raw) > MAX_EDITS:
        raise AnnotationError(f"edits must be a list of at most {MAX_EDITS} items")
    edits = tuple(_edit(item, index) for index, item in enumerate(edits_raw))
    ids = [edit.id for edit in edits]
    if len(set(ids)) != len(ids):
        raise AnnotationError("edit ids must be unique")
    return Annotations(
        image=image.strip(),
        image_version=version,
        composite_to_original=composite,
        global_note=_text(doc.get("global_note"), "global_note", limit=MAX_NOTE_CHARS),
        edits=edits,
    )


REPORT_STATUSES = ("done", "not_done", "partial")
MAX_REASON_CHARS = 300


def parse_report(raw: object) -> list[dict[str, Any]]:
    """The agent's per-region report (IM-13): region id, status, and a short reason. Empty when absent."""
    if raw is None:
        return []
    items = _as_list(raw)
    if items is None or len(items) > MAX_EDITS:
        raise AnnotationError(f"report must be a list of at most {MAX_EDITS} items")
    report: list[dict[str, Any]] = []
    for index, item in enumerate(items):
        entry = _as_dict(item)
        if entry is None:
            raise AnnotationError(f"report[{index}] must be an object")
        region_id = entry.get("id")
        if isinstance(region_id, bool) or not isinstance(region_id, int) or region_id < 1:
            raise AnnotationError(f"report[{index}].id must be a positive integer")
        status = entry.get("status")
        if status not in REPORT_STATUSES:
            raise AnnotationError(f"report[{index}].status must be one of {', '.join(REPORT_STATUSES)}")
        reason = _text(entry.get("reason"), f"report[{index}].reason", limit=MAX_REASON_CHARS)
        report.append({"id": region_id, "status": status, "reason": reason})
    return report


def describe(annotations: Annotations) -> list[dict[str, Any]]:
    """A compact per-region view for the model: id, shape, where, and the note."""
    out: list[dict[str, Any]] = []
    for edit in annotations.edits:
        entry: dict[str, Any] = {"id": edit.id, "shape": edit.shape, "note": edit.note}
        if edit.box is not None:
            entry["box"] = list(edit.box)
        if edit.point is not None:
            entry["point"] = list(edit.point)
        if edit.shape == "brush":
            entry["stroke_points"] = len(edit.points)
            entry["radius"] = edit.radius
            if edit.erase:
                entry["erase"] = True
        out.append(entry)
    return out

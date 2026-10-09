"""Image review (Phase 9): annotation validation, deterministic masks and compositing, temporary versions,
and the composite tool's workspace boundary."""

from __future__ import annotations

import io
import json
import os
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from nanobot.coworker.config import ImageReviewConfig
from nanobot.coworker.image import raster, versions
from nanobot.coworker.image.annotations import MAX_EDITS, SCHEMA, AnnotationError, parse_annotations
from nanobot.coworker.image.tools import ImageCompositeTool, _resolve


def _png(size: tuple[int, int], color: tuple[int, int, int]) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, format="PNG")
    return buffer.getvalue()


def _doc(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {"schema": SCHEMA, "image": "assets/banner.png", "edits": []}
    base.update(overrides)
    return base


# ---------- annotations ----------

def test_a_valid_payload_is_normalised() -> None:
    doc = parse_annotations(_doc(edits=[
        {"id": 1, "shape": "rect", "box": [0.9, 0.1, 0.2, 0.4], "note": "logo"},
        {"id": 2, "shape": "pin", "point": [0.5, 0.5], "note": "add text here"},
        {"id": 3, "shape": "brush", "points": [[0.1, 0.1], [0.2, 0.2]], "radius": 0.02, "note": "remove person"},
    ]))
    rect = doc.edits[0]
    assert rect.box == (0.2, 0.1, 0.9, 0.4)  # corners sorted
    assert doc.composite_to_original is True
    assert [e.shape for e in doc.edits] == ["rect", "pin", "brush"]


@pytest.mark.parametrize("bad", [
    {"schema": "other"},
    {"image": ""},
    {"edits": [{"id": 1, "shape": "triangle", "note": ""}]},
    {"edits": [{"id": 1, "shape": "rect", "box": [0, 0, 1.5, 1]}]},
    {"edits": [{"id": 1, "shape": "pin", "point": [0.5]}]},
    {"edits": [{"id": 1, "shape": "brush", "points": [], "radius": 0.02}]},
    {"edits": [{"id": 1, "shape": "brush", "points": [[0.1, 0.1]], "radius": 0.9}]},
    {"edits": [{"id": 1, "shape": "rect", "box": [0, 0, 1, 1]}, {"id": 1, "shape": "rect", "box": [0, 0, 1, 1]}]},
    {"edits": [{"id": 1, "shape": "rect", "box": [0, 0, 1, 1], "note": "x" * 1001}]},
    {"composite_to_original": "yes"},
])
def test_malformed_payloads_are_rejected(bad: dict[str, object]) -> None:
    with pytest.raises(AnnotationError):
        parse_annotations(_doc(**bad))


def test_too_many_regions_are_rejected() -> None:
    edits = [{"id": i + 1, "shape": "pin", "point": [0.1, 0.1]} for i in range(MAX_EDITS + 1)]
    with pytest.raises(AnnotationError):
        parse_annotations(_doc(edits=edits))


def test_booleans_are_not_numbers() -> None:
    with pytest.raises(AnnotationError):
        parse_annotations(_doc(edits=[{"id": 1, "shape": "pin", "point": [True, 0.5]}]))


# ---------- raster ----------

def test_a_rectangle_mask_covers_its_box_and_nothing_else() -> None:
    doc = parse_annotations(_doc(edits=[{"id": 1, "shape": "rect", "box": [0.25, 0.25, 0.75, 0.75]}]))
    mask = raster.region_mask(doc, (100, 100))
    assert mask.getpixel((50, 50)) == 255
    assert mask.getpixel((5, 5)) == 0
    assert mask.getpixel((95, 95)) == 0


def test_an_ellipse_leaves_the_corners_out() -> None:
    doc = parse_annotations(_doc(edits=[{"id": 1, "shape": "ellipse", "box": [0.1, 0.1, 0.9, 0.9]}]))
    mask = raster.region_mask(doc, (100, 100))
    assert mask.getpixel((50, 50)) == 255
    assert mask.getpixel((12, 12)) == 0


def test_a_brush_stroke_marks_its_path() -> None:
    doc = parse_annotations(_doc(edits=[
        {"id": 1, "shape": "brush", "points": [[0.1, 0.5], [0.9, 0.5]], "radius": 0.03},
    ]))
    mask = raster.region_mask(doc, (100, 100))
    assert mask.getpixel((50, 50)) == 255
    assert mask.getpixel((50, 10)) == 0


def test_composite_keeps_original_pixels_outside_the_mask() -> None:
    original = Image.new("RGBA", (100, 100), (0, 0, 255, 255))
    edited = Image.new("RGBA", (100, 100), (255, 0, 0, 255))
    doc = parse_annotations(_doc(edits=[{"id": 1, "shape": "rect", "box": [0.4, 0.4, 0.6, 0.6]}]))
    result = raster.composite(original, edited, raster.region_mask(doc, original.size))
    assert result.getpixel((50, 50))[:3] == (255, 0, 0)  # inside: edited
    assert result.getpixel((5, 5))[:3] == (0, 0, 255)  # outside: untouched


def test_text_is_drawn_inside_its_box_with_a_real_font() -> None:
    font = next((p for p in (Path("C:/Windows/Fonts/arial.ttf"), Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")) if p.is_file()), None)
    if font is None:
        pytest.skip("no TrueType font on this machine")
    base = Image.new("RGBA", (300, 120), (255, 255, 255, 255))
    out = raster.draw_text(base, "Ưu đãi tháng 10", (0.1, 0.2, 0.9, 0.8), font)
    changed = any(out.getpixel((x, y))[:3] != (255, 255, 255) for x in range(out.width) for y in range(out.height))
    assert changed  # something was drawn
    assert all(out.getpixel((x, y))[:3] == (255, 255, 255) for x, y in [(2, 2), (298, 118)])


# ---------- versions ----------

def test_a_version_round_trips_for_its_own_session_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(versions, "version_root", lambda: tmp_path / "versions")
    saved = versions.save_version("websocket:a", _png((8, 6), (1, 2, 3)))
    assert (saved.width, saved.height) == (8, 6)
    assert versions.resolve_version("websocket:a", saved.id) == saved.path
    assert versions.resolve_version("websocket:b", saved.id) is None


def test_malformed_version_ids_never_resolve(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(versions, "version_root", lambda: tmp_path / "versions")
    versions.save_version("websocket:a", _png((4, 4), (0, 0, 0)))
    for bad in ("../../etc/passwd", "ABCDEF", "g" * 32, ""):
        assert versions.resolve_version("websocket:a", bad) is None


def test_only_images_are_stored(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(versions, "version_root", lambda: tmp_path / "versions")
    with pytest.raises(versions.VersionError):
        versions.save_version("websocket:a", b"<html>not an image</html>")


def test_purge_removes_a_session_and_stale_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(versions, "version_root", lambda: tmp_path / "versions")
    kept = versions.save_version("websocket:a", _png((4, 4), (9, 9, 9)))
    gone = versions.save_version("websocket:b", _png((4, 4), (8, 8, 8)))
    versions.purge_session("websocket:b")
    assert versions.resolve_version("websocket:b", gone.id) is None
    old = time.time() - 10 * 24 * 3600
    os.utime(kept.path, (old, old))
    assert versions.purge_stale(max_age_seconds=24 * 3600) == 1
    assert not kept.path.exists()


# ---------- tool boundary ----------

def test_paths_outside_the_project_are_refused(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    outside = tmp_path / "secret.png"
    outside.write_bytes(_png((4, 4), (1, 1, 1)))
    (project / "inside.png").write_bytes(_png((4, 4), (1, 1, 1)))
    assert _resolve("inside.png", project).name == "inside.png"
    with pytest.raises(ValueError):
        _resolve(str(outside), project)
    with pytest.raises(ValueError):
        _resolve("../secret.png", project)


async def test_composite_tool_stores_a_version_and_respects_the_mask(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "orig.png").write_bytes(_png((40, 40), (0, 0, 255)))
    (project / "edit.png").write_bytes(_png((40, 40), (255, 0, 0)))
    (project / "ann.json").write_text(json.dumps(_doc(
        image="orig.png", edits=[{"id": 1, "shape": "rect", "box": [0.25, 0.25, 0.75, 0.75]}],
    )), encoding="utf-8")
    monkeypatch.setattr(versions, "version_root", lambda: tmp_path / "versions")

    tool = ImageCompositeTool()
    monkeypatch.setattr(tool, "_context", lambda: (project, ImageReviewConfig(enabled=True)))
    monkeypatch.setattr(tool, "_session_key", lambda: "websocket:a")
    result = await tool.execute(original="orig.png", edited="edit.png", annotations="ann.json")
    payload = json.loads(str(result.content if hasattr(result, "content") else result))
    assert payload["status"] == "version"
    stored = versions.resolve_version("websocket:a", payload["version"])
    assert stored is not None
    with Image.open(stored) as image:
        rgb = image.convert("RGB")
        assert rgb.getpixel((2, 2)) == (0, 0, 255)  # outside the box: original
        assert rgb.getpixel((20, 20)) == (255, 0, 0)  # inside the box: edited


async def test_image_tools_are_off_until_the_setting_is_on(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    tool = ImageCompositeTool()
    monkeypatch.setattr(
        "nanobot.coworker.image.tools.load_coworker_config",
        lambda: SimpleNamespace(image=ImageReviewConfig(enabled=False)),
    )
    monkeypatch.setattr("nanobot.coworker.image.tools.project_root_for", lambda session: tmp_path)
    monkeypatch.setattr(tool, "session", lambda: object())
    assert tool._context() == "image review is not enabled"

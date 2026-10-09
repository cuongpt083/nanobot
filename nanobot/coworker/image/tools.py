"""Image review tools (Phase 9): read the annotations, edit a region, composite it back, render text,
and keep a version. The tools do the deterministic work; the image-region-edit skill decides the edit."""

# pyright: reportIncompatibleMethodOverride=false

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any

from PIL import Image

from nanobot.agent.tools.base import ToolResult, tool_parameters
from nanobot.config.paths import get_media_dir
from nanobot.coworker.advisor.tool import project_root_for
from nanobot.coworker.config import ImageReviewConfig, load_coworker_config
from nanobot.coworker.image import raster, versions
from nanobot.coworker.image.annotations import (
    AnnotationError,
    describe,
    parse_annotations,
    parse_report,
)
from nanobot.coworker.tools_base import CoworkerTool
from nanobot.security.workspace_policy import WorkspaceBoundaryError, resolve_allowed_path

IMAGE_READ_TOOL = "image_annotations_read"
IMAGE_EDIT_TOOL = "image_edit"
IMAGE_COMPOSITE_TOOL = "image_composite"
IMAGE_TEXT_TOOL = "render_text"
IMAGE_VERSION_TOOL = "image_version_save"
IMAGE_TOOLS = frozenset({IMAGE_READ_TOOL, IMAGE_EDIT_TOOL, IMAGE_COMPOSITE_TOOL, IMAGE_TEXT_TOOL, IMAGE_VERSION_TOOL})

_FONT_CANDIDATES = (
    Path("C:/Windows/Fonts/arial.ttf"),
    Path("/Library/Fonts/Arial.ttf"),
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
)


def _font_path(config: ImageReviewConfig) -> Path | None:
    if config.font_path:
        return Path(config.font_path).expanduser()
    return next((path for path in _FONT_CANDIDATES if path.is_file()), None)


def _resolve(raw: str, root: Path, *, extra_roots: list[Path] | None = None) -> Path:
    """A file inside the project (or the nanobot media folder). Raises ``ValueError`` otherwise."""
    if not raw or not raw.strip():
        raise ValueError("path is required")
    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = root / candidate
    try:
        resolved = resolve_allowed_path(
            candidate, workspace=root, allowed_root=root,
            extra_allowed_roots=extra_roots, strict=True,
        )
    except WorkspaceBoundaryError as exc:
        raise ValueError("path is outside the project") from exc
    except OSError as exc:
        raise ValueError(f"not found: {raw}") from exc
    if not resolved.is_file():
        raise ValueError(f"not a file: {raw}")
    return resolved


def _png_bytes(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


class _ImageTool(CoworkerTool):
    """Shared plumbing: the session's project root and the image review settings."""

    def _context(self) -> tuple[Path, ImageReviewConfig] | str:
        session = self.session()
        if session is None:
            return "no active session"
        root = project_root_for(session)
        if root is None:
            return "no project directory for this session"
        config = load_coworker_config().image
        if not config.enabled:
            return "image review is not enabled"
        return root, config

    def _session_key(self) -> str:
        request = self.request()
        return (request.session_key or "") if request is not None else ""


@tool_parameters({
    "type": "object",
    "properties": {"path": {"type": "string", "description": "Project path of the annotation JSON file."}},
    "required": ["path"],
})
class ImageAnnotationsReadTool(_ImageTool):
    @property
    def name(self) -> str:
        return IMAGE_READ_TOOL

    @property
    def description(self) -> str:
        return (
            "Read an image annotation file (schema nanobot.image-annotations/v1). Returns the image path, the "
            "global note and each region: id, shape (rect, ellipse, brush or pin), where it is (box as "
            "[x0, y0, x1, y1] or point as [x, y], fractions of the image), and the user's note. Notes are "
            "instructions from the user about the picture; the coordinates are not to be drawn."
        )

    @property
    def read_only(self) -> bool:
        return True

    async def execute(self, path: str = "", **kwargs: Any) -> ToolResult:
        ctx = self._context()
        if isinstance(ctx, str):
            return self.payload("error", error=ctx)
        root, _ = ctx
        try:
            target = _resolve(path, root)
            annotations = parse_annotations(json.loads(target.read_text(encoding="utf-8")))
        except (ValueError, AnnotationError, OSError) as exc:
            return self.payload("error", error=str(exc))
        return self.payload(
            "ok",
            image=annotations.image,
            image_version=annotations.image_version,
            composite_to_original=annotations.composite_to_original,
            global_note=annotations.global_note,
            regions=describe(annotations),
        )


@tool_parameters({
    "type": "object",
    "properties": {
        "source": {"type": "string", "description": "Project path of the image to edit."},
        "prompt": {
            "type": "string",
            "description": (
                "English instruction for the image model: what to change, and that the frames and numbers "
                "are annotations that must not be drawn."
            ),
        },
    },
    "required": ["source", "prompt"],
})
class ImageEditTool(_ImageTool):
    @property
    def name(self) -> str:
        return IMAGE_EDIT_TOOL

    @property
    def description(self) -> str:
        return (
            "Ask the configured image model to edit a picture. Returns the path of the edited image. Pass the "
            "result to image_composite so that only the annotated regions change."
        )

    async def execute(self, source: str = "", prompt: str = "", **kwargs: Any) -> ToolResult:
        from nanobot.agent.tools.image_generation import ImageGenerationTool
        from nanobot.config.loader import load_config
        from nanobot.providers.image_generation import image_gen_provider_configs

        ctx = self._context()
        if isinstance(ctx, str):
            return self.payload("error", error=ctx)
        root, _ = ctx
        if not prompt.strip():
            return self.payload("error", error="prompt is required")
        try:
            image = _resolve(source, root)
        except ValueError as exc:
            return self.payload("error", error=str(exc))
        config = load_config()
        # The repo builds this tool directly the same way; the abstract-class report is a pyright artefact.
        tool = ImageGenerationTool(  # pyright: ignore[reportAbstractUsage]
            workspace=root,
            config=config.tools.image_generation,
            provider_configs=image_gen_provider_configs(config),
        )
        result = await tool.execute(prompt=prompt, reference_images=[str(image)])
        try:
            parsed = json.loads(str(result))
            edited = str(parsed["artifacts"][0]["path"])
        except (ValueError, KeyError, IndexError, TypeError):
            return self.payload("error", error=f"image model returned no image: {result}")
        return self.payload("edited", path=edited)


@tool_parameters({
    "type": "object",
    "properties": {
        "original": {"type": "string", "description": "Project path of the image the user annotated."},
        "edited": {"type": "string", "description": "Path of the edited image (from image_edit)."},
        "annotations": {"type": "string", "description": "Project path of the annotation JSON file."},
        "report": {
            "type": "array",
            "description": (
                "Your per-region report: a list of {id, status, reason} where status is done, not_done or partial "
                "and reason is one short sentence. Pass the region numbers the user saw."
            ),
        },
    },
    "required": ["original", "edited", "annotations"],
})
class ImageCompositeTool(_ImageTool):
    @property
    def name(self) -> str:
        return IMAGE_COMPOSITE_TOOL

    @property
    def description(self) -> str:
        return (
            "Keep the edited pixels only inside the annotated regions, using the original everywhere else, and "
            "store the result as a version. If composite_to_original is false in the annotations, the edited "
            "image is stored as it is."
        )

    async def execute(
        self,
        original: str = "",
        edited: str = "",
        annotations: str = "",
        report: list[Any] | None = None,
        **kwargs: Any,
    ) -> ToolResult:
        ctx = self._context()
        if isinstance(ctx, str):
            return self.payload("error", error=ctx)
        root, _ = ctx
        try:
            regions_report = parse_report(report)
            original_path = _resolve(original, root)
            edited_path = _resolve(edited, root, extra_roots=[get_media_dir()])
            raw_annotations: dict[str, Any] = json.loads(_resolve(annotations, root).read_text(encoding="utf-8"))
            doc = parse_annotations(raw_annotations)
            with Image.open(original_path) as base_probe:
                base = base_probe.convert("RGBA")
            with Image.open(edited_path) as edit_probe:
                edit = edit_probe.convert("RGBA")
            if doc.composite_to_original:
                mask = raster.region_mask(doc, base.size)
                if not mask.getbbox():
                    return self.payload("error", error="no annotated region to keep")
                result = raster.composite(base, edit, mask)
            else:
                result = edit
            data = _png_bytes(result)
            source = versions.source_key(original, root)
        except (ValueError, AnnotationError, OSError, raster.RasterError, versions.VersionError) as exc:
            return self.payload("error", error=str(exc))
        saved = versions.save_version(
            self._session_key(), data, source=source, report=regions_report, annotation=raw_annotations,
        )
        return self.payload("version", version=saved.id, width=saved.width, height=saved.height)


@tool_parameters({
    "type": "object",
    "properties": {
        "image": {"type": "string", "description": "Project path of the image."},
        "text": {"type": "string", "description": "The text to draw. Unicode, including Vietnamese, is supported."},
        "box": {
            "type": "array", "items": {"type": "number"}, "minItems": 4, "maxItems": 4,
            "description": "[x0, y0, x1, y1] fractions of the image where the text goes.",
        },
    },
    "required": ["image", "text", "box"],
})
class RenderTextTool(_ImageTool):
    @property
    def name(self) -> str:
        return IMAGE_TEXT_TOOL

    @property
    def description(self) -> str:
        return "Draw text onto an image with a real font, shrunk to fit the box, and store the result as a version."

    async def execute(self, image: str = "", text: str = "", box: list[float] | None = None, **kwargs: Any) -> ToolResult:
        ctx = self._context()
        if isinstance(ctx, str):
            return self.payload("error", error=ctx)
        root, config = ctx
        font = _font_path(config)
        if font is None:
            return self.payload("error", error="no font available: set coworker.image.fontPath")
        if not box or len(box) != 4:
            return self.payload("error", error="box must be [x0, y0, x1, y1]")
        x0, y0, x1, y1 = (float(v) for v in box)
        if not all(0 <= v <= 1 for v in (x0, y0, x1, y1)):
            return self.payload("error", error="box values must be between 0 and 1")
        try:
            source = _resolve(image, root)
            with Image.open(source) as probe:
                drawn = raster.draw_text(
                    probe.convert("RGBA"), text,
                    (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)), font,
                )
            data = _png_bytes(drawn)
            source_name = versions.source_key(image, root)
        except (ValueError, OSError, raster.RasterError, versions.VersionError) as exc:
            return self.payload("error", error=str(exc))
        saved = versions.save_version(self._session_key(), data, source=source_name)
        return self.payload("version", version=saved.id, width=saved.width, height=saved.height)


@tool_parameters({
    "type": "object",
    "properties": {
        "image": {"type": "string", "description": "Project path of the image to keep."},
        "report": {
            "type": "array",
            "description": (
                "Your per-region report: a list of {id, status, reason} where status is done, not_done or partial "
                "and reason is one short sentence. Pass the region numbers the user saw."
            ),
        },
    },
    "required": ["image"],
})
class ImageVersionSaveTool(_ImageTool):
    @property
    def name(self) -> str:
        return IMAGE_VERSION_TOOL

    @property
    def description(self) -> str:
        return "Store a project image as a temporary version (for before/after comparison in the review pane)."

    async def execute(self, image: str = "", report: list[Any] | None = None, **kwargs: Any) -> ToolResult:
        ctx = self._context()
        if isinstance(ctx, str):
            return self.payload("error", error=ctx)
        root, _ = ctx
        try:
            regions_report = parse_report(report)
            data = _resolve(image, root).read_bytes()
            source_name = versions.source_key(image, root)
            saved = versions.save_version(self._session_key(), data, source=source_name, report=regions_report)
        except (ValueError, OSError, AnnotationError, versions.VersionError) as exc:
            return self.payload("error", error=str(exc))
        return self.payload("version", version=saved.id, width=saved.width, height=saved.height)

"""Deterministic pixel work for image edits: region masks, compositing, and text.

The model decides what to change; these functions decide where the change may land. The mask is built
from the same annotation the user drew, so a model that edits more than the region still cannot alter
pixels outside it when ``composite_to_original`` is on.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from nanobot.coworker.image.annotations import Annotations, Edit

PIN_RADIUS = 0.06  # fraction of the shorter side; a pin marks where something is added
FEATHER_PX = 2


class RasterError(ValueError):
    """The image or request cannot be processed."""


def _px(point: tuple[float, float], size: tuple[int, int]) -> tuple[float, float]:
    return point[0] * size[0], point[1] * size[1]


def _draw_edit(draw: ImageDraw.ImageDraw, edit: Edit, size: tuple[int, int]) -> None:
    short = min(size)
    if edit.shape == "rect" and edit.box is not None:
        x0, y0, x1, y1 = edit.box
        draw.rectangle([x0 * size[0], y0 * size[1], x1 * size[0], y1 * size[1]], fill=255)
    elif edit.shape == "ellipse" and edit.box is not None:
        x0, y0, x1, y1 = edit.box
        draw.ellipse([x0 * size[0], y0 * size[1], x1 * size[0], y1 * size[1]], fill=255)
    elif edit.shape == "brush":
        radius = edit.radius * short
        pixels = [_px(p, size) for p in edit.points]
        if len(pixels) > 1:
            draw.line(pixels, fill=255, width=max(1, int(radius * 2)), joint="curve")
        for x, y in pixels:
            draw.ellipse([x - radius, y - radius, x + radius, y + radius], fill=255)
    elif edit.shape == "pin" and edit.point is not None:
        x, y = _px(edit.point, size)
        radius = PIN_RADIUS * short
        draw.ellipse([x - radius, y - radius, x + radius, y + radius], fill=255)


def region_mask(annotations: Annotations, size: tuple[int, int]) -> Image.Image:
    """A grayscale mask (255 inside any region) at the original image's size."""
    if size[0] <= 0 or size[1] <= 0:
        raise RasterError("image has no size")
    mask = Image.new("L", size, 0)
    draw = ImageDraw.Draw(mask)
    for edit in annotations.edits:
        _draw_edit(draw, edit, size)
    return mask


def composite(original: Image.Image, edited: Image.Image, mask: Image.Image) -> Image.Image:
    """Keep the edited pixels inside the mask and the original everywhere else (soft edge)."""
    base = original.convert("RGBA")
    candidate: Image.Image = edited.convert("RGBA")
    target: tuple[int, int] = (int(base.width), int(base.height))
    if (int(candidate.width), int(candidate.height)) != target:
        # Pillow's stub leaves the size parameter partly unknown; the tuple here is fully typed.
        candidate = Image.Image.resize(candidate, target, Image.Resampling.LANCZOS)  # pyright: ignore[reportUnknownMemberType]
    soft = mask.filter(ImageFilter.GaussianBlur(FEATHER_PX))
    return Image.composite(candidate, base, soft)


def _font(font_path: Path, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    try:
        return ImageFont.truetype(str(font_path), size)
    except OSError as exc:
        raise RasterError(f"font not readable: {font_path}") from exc


def draw_text(
    image: Image.Image,
    text: str,
    box: tuple[float, float, float, float],
    font_path: Path,
    color: tuple[int, int, int, int] = (0, 0, 0, 255),
) -> Image.Image:
    """Draw one line of text, shrunk to fit a normalised box, with the given font (Unicode, incl. Vietnamese)."""
    if not text.strip():
        raise RasterError("text is empty")
    out = image.convert("RGBA")
    width_px = (box[2] - box[0]) * out.width
    height_px = (box[3] - box[1]) * out.height
    if width_px <= 0 or height_px <= 0:
        raise RasterError("text box has no area")
    size = max(8, int(height_px))
    while size > 8:
        font = _font(font_path, size)
        left, top, right, bottom = ImageDraw.Draw(out).textbbox((0, 0), text, font=font)
        if right - left <= width_px and bottom - top <= height_px:
            break
        size -= 2
    font = _font(font_path, size)
    left, top, right, bottom = ImageDraw.Draw(out).textbbox((0, 0), text, font=font)
    x = box[0] * out.width + (width_px - (right - left)) / 2 - left
    y = box[1] * out.height + (height_px - (bottom - top)) / 2 - top
    ImageDraw.Draw(out).text((x, y), text, font=font, fill=color)
    return out

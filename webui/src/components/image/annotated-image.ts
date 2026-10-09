/**
 * The picture the agent is sent alongside the annotation file: the image itself with each region drawn in
 * its colour and numbered, the way the pane shows it (IM-11). It is rendered at the image's own size, capped
 * for the transport, so the agent sees the marks at the same places the annotation file has them.
 */
import { BRUSH_SIZES, regionColor, type AnnotationDoc, type Region } from "@/components/image/annotation-model";

export const ANNOTATED_MAX_SIDE = 1600;
/** Larger than this, the picture is re-encoded as JPEG so one message stays within the transport limit. */
export const ANNOTATED_MAX_DATA_URL_CHARS = 4_000_000;

function drawRegion(ctx: CanvasRenderingContext2D, region: Region, width: number, height: number, short: number) {
  const color = regionColor(region);
  const lineWidth = Math.max(2, short * 0.004);
  let anchor: [number, number] | null = null;
  ctx.save();
  ctx.strokeStyle = color;
  ctx.fillStyle = color;
  if ((region.shape === "rect" || region.shape === "ellipse") && region.box) {
    const [x0, y0, x1, y1] = region.box;
    const left = x0 * width;
    const top = y0 * height;
    const w = (x1 - x0) * width;
    const h = (y1 - y0) * height;
    ctx.lineWidth = lineWidth;
    if (region.erase) ctx.setLineDash([lineWidth * 3, lineWidth * 2]);
    ctx.beginPath();
    if (region.shape === "rect") {
      ctx.rect(left, top, w, h);
    } else {
      ctx.ellipse(left + w / 2, top + h / 2, w / 2, h / 2, 0, 0, Math.PI * 2);
    }
    ctx.stroke();
    anchor = [left, top];
  } else if (region.shape === "brush" && region.points?.length) {
    ctx.globalAlpha = region.erase ? 0.6 : 0.4;
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    ctx.lineWidth = 2 * (region.radius ?? BRUSH_SIZES.M) * short;
    ctx.beginPath();
    region.points.forEach(([px, py], index) => {
      if (index === 0) ctx.moveTo(px * width, py * height);
      else ctx.lineTo(px * width, py * height);
    });
    if (region.points.length === 1) ctx.lineTo(region.points[0][0] * width, region.points[0][1] * height);
    ctx.stroke();
    ctx.globalAlpha = 1;
    anchor = [region.points[0][0] * width, region.points[0][1] * height];
  } else if (region.shape === "pin" && region.point) {
    const [px, py] = region.point;
    const radius = Math.max(6, short * 0.012);
    ctx.beginPath();
    ctx.arc(px * width, py * height, radius, 0, Math.PI * 2);
    ctx.fill();
    ctx.lineWidth = 2;
    ctx.strokeStyle = "#ffffff";
    ctx.stroke();
    anchor = [px * width, py * height];
  }
  if (anchor) {
    const size = Math.max(14, short * 0.03);
    ctx.font = `bold ${size}px sans-serif`;
    ctx.fillStyle = color;
    ctx.textBaseline = "top";
    ctx.fillText(String(region.id), anchor[0] + size * 0.3, anchor[1] + size * 0.3);
  }
  ctx.restore();
}

/** The image with its regions drawn on it, as a data URL; ``null`` when there is no canvas to draw on. */
export function renderAnnotatedImage(image: HTMLImageElement, doc: AnnotationDoc): string | null {
  const naturalWidth = image.naturalWidth;
  const naturalHeight = image.naturalHeight;
  if (!naturalWidth || !naturalHeight) return null;
  const scale = Math.min(1, ANNOTATED_MAX_SIDE / Math.max(naturalWidth, naturalHeight));
  const width = Math.max(1, Math.round(naturalWidth * scale));
  const height = Math.max(1, Math.round(naturalHeight * scale));
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const ctx = canvas.getContext("2d");
  if (!ctx) return null;
  ctx.drawImage(image, 0, 0, width, height);
  const short = Math.min(width, height);
  for (const region of doc.regions) drawRegion(ctx, region, width, height, short);
  const png = canvas.toDataURL("image/png");
  return png.length <= ANNOTATED_MAX_DATA_URL_CHARS ? png : canvas.toDataURL("image/jpeg", 0.85);
}

/** A file name for the picture: the image's own name, marked as annotated. */
export function annotatedPictureName(imagePath: string, dataUrl: string): string {
  const base = (imagePath.split("/").pop() ?? "image").replace(/\.[^.]+$/, "");
  const extension = dataUrl.startsWith("data:image/png") ? "png" : "jpg";
  return `${base}.annotated.${extension}`;
}

/**
 * The annotations a user draws on an image, as plain data (Phase 9, IM-01…IM-11).
 *
 * Every coordinate is a fraction (0–1) of the original image, so the same document is valid at any zoom.
 * Undo and redo keep whole snapshots: documents are small (a few dozen regions at most).
 */

export type RegionShape = "rect" | "ellipse" | "brush" | "pin";
export type Box = [number, number, number, number];
export type Pair = [number, number];

export interface Region {
  id: number;
  shape: RegionShape;
  note: string;
  box?: Box;
  points?: Pair[];
  radius?: number;
  point?: Pair;
  /** A brush stroke that removes from the marked area (eraser, IM-04). */
  erase?: boolean;
}

export interface AnnotationDoc {
  regions: Region[];
  globalNote: string;
  compositeToOriginal: boolean;
  /** The next number to hand out; numbers are never reused after a region is removed. */
  nextId: number;
}

export interface History {
  past: AnnotationDoc[];
  present: AnnotationDoc;
  future: AnnotationDoc[];
}

export const SCHEMA = "nanobot.image-annotations/v1";
const HISTORY_LIMIT = 100;
export const MIN_BOX = 0.005;
export const BRUSH_RADIUS = 0.02;
/** Brush sizes as fractions of the shorter image side; the middle one is the default. */
export const BRUSH_SIZES = { S: 0.01, M: 0.02, L: 0.04 } as const;
export type BrushSize = keyof typeof BRUSH_SIZES;
/** Matches the server's limits, so an annotation the pane builds is always accepted. */
export const MAX_REGIONS = 50;
export const MAX_NOTE_CHARS = 1_000;
export const MAX_BRUSH_POINTS = 2_000;

export function emptyDoc(): AnnotationDoc {
  return { regions: [], globalNote: "", compositeToOriginal: true, nextId: 1 };
}

export function createHistory(doc: AnnotationDoc = emptyDoc()): History {
  return { past: [], present: doc, future: [] };
}

/** Record a change so it can be undone. A no-op change is not recorded. */
export function commit(history: History, next: AnnotationDoc): History {
  if (next === history.present) return history;
  const past = [...history.past, history.present];
  return {
    past: past.length > HISTORY_LIMIT ? past.slice(past.length - HISTORY_LIMIT) : past,
    present: next,
    future: [],
  };
}

export function undo(history: History): History {
  const previous = history.past[history.past.length - 1];
  if (!previous) return history;
  return { past: history.past.slice(0, -1), present: previous, future: [history.present, ...history.future] };
}

export function redo(history: History): History {
  const [next, ...rest] = history.future;
  if (!next) return history;
  return { past: [...history.past, history.present], present: next, future: rest };
}

export function canAddRegion(doc: AnnotationDoc): boolean {
  return doc.regions.length < MAX_REGIONS;
}

/** Add a region with the next number. Returns the document unchanged when the limit is reached. */
export function addRegion(doc: AnnotationDoc, shape: Omit<Region, "id" | "note"> & { note?: string }): AnnotationDoc {
  if (!canAddRegion(doc)) return doc;
  const region: Region = { ...shape, id: doc.nextId, note: shape.note ?? "" };
  return { ...doc, regions: [...doc.regions, region], nextId: doc.nextId + 1 };
}

export function setNote(doc: AnnotationDoc, id: number, note: string): AnnotationDoc {
  const clipped = note.slice(0, MAX_NOTE_CHARS);
  const regions = doc.regions.map((region) => (region.id === id ? { ...region, note: clipped } : region));
  return { ...doc, regions };
}

export function removeRegion(doc: AnnotationDoc, id: number): AnnotationDoc {
  return { ...doc, regions: doc.regions.filter((region) => region.id !== id) };
}

export function setGlobalNote(doc: AnnotationDoc, note: string): AnnotationDoc {
  return { ...doc, globalNote: note.slice(0, MAX_NOTE_CHARS) };
}

export function setCompositeToOriginal(doc: AnnotationDoc, value: boolean): AnnotationDoc {
  return { ...doc, compositeToOriginal: value };
}

/** A box from two corners in fractions, sorted and clamped to the image. Null when too small to matter. */
export function boxFromCorners(a: Pair, b: Pair): Box | null {
  const clamp = (v: number) => Math.min(1, Math.max(0, v));
  const x0 = clamp(Math.min(a[0], b[0]));
  const y0 = clamp(Math.min(a[1], b[1]));
  const x1 = clamp(Math.max(a[0], b[0]));
  const y1 = clamp(Math.max(a[1], b[1]));
  if (x1 - x0 < MIN_BOX || y1 - y0 < MIN_BOX) return null;
  return [x0, y0, x1, y1];
}

/** The annotation file as the server reads it (schema nanobot.image-annotations/v1). */
export function toPayload(doc: AnnotationDoc, image: string, imageVersion: string | null) {
  return {
    schema: SCHEMA,
    image,
    image_version: imageVersion,
    composite_to_original: doc.compositeToOriginal,
    global_note: doc.globalNote,
    edits: doc.regions.map((region) => {
      const base = { id: region.id, shape: region.shape, note: region.note };
      if (region.shape === "brush") {
        const stroke = { ...base, points: region.points ?? [], radius: region.radius ?? BRUSH_RADIUS };
        return region.erase ? { ...stroke, erase: true } : stroke;
      }
      if (region.shape === "pin") return { ...base, point: region.point ?? [0, 0] };
      return { ...base, box: region.box ?? [0, 0, 0, 0] };
    }),
  };
}

export function regionLabel(region: Region): string {
  const shapes: Record<RegionShape, string> = { rect: "rectangle", ellipse: "ellipse", brush: "brush", pin: "pin" };
  const kind = region.erase ? "eraser" : shapes[region.shape];
  return `${region.id} · ${kind}`;
}

const clamp01 = (value: number) => Math.min(1, Math.max(0, value));

/** Move a region by a fraction offset. Size is kept; the region stays inside the image. */
export function moveRegion(doc: AnnotationDoc, id: number, dx: number, dy: number): AnnotationDoc {
  const regions = doc.regions.map((region): Region => {
    if (region.id !== id) return region;
    if (region.box) {
      const [x0, y0, x1, y1] = region.box;
      const ox = Math.min(Math.max(dx, -x0), 1 - x1);
      const oy = Math.min(Math.max(dy, -y0), 1 - y1);
      return { ...region, box: [x0 + ox, y0 + oy, x1 + ox, y1 + oy] };
    }
    if (region.point) {
      return { ...region, point: [clamp01(region.point[0] + dx), clamp01(region.point[1] + dy)] };
    }
    if (region.points?.length) {
      const xs = region.points.map(([x]) => x);
      const ys = region.points.map(([, y]) => y);
      const ox = Math.min(Math.max(dx, -Math.min(...xs)), 1 - Math.max(...xs));
      const oy = Math.min(Math.max(dy, -Math.min(...ys)), 1 - Math.max(...ys));
      return { ...region, points: region.points.map(([x, y]): Pair => [x + ox, y + oy]) };
    }
    return region;
  });
  return { ...doc, regions };
}

/** Corners of a box in order: top-left, top-right, bottom-right, bottom-left. */
export type Corner = 0 | 1 | 2 | 3;

export function boxCorners(box: Box): Pair[] {
  const [x0, y0, x1, y1] = box;
  return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]];
}

/** Drag one corner of a rectangle or ellipse. The opposite corner stays where it is. */
export function resizeBox(doc: AnnotationDoc, id: number, corner: Corner, to: Pair): AnnotationDoc {
  const regions = doc.regions.map((region): Region => {
    if (region.id !== id || !region.box) return region;
    // The corner diagonally opposite the one being dragged is the fixed anchor.
    const anchor = boxCorners(region.box)[(corner + 2) % 4];
    const box = boxFromCorners([clamp01(to[0]), clamp01(to[1])], anchor);
    return box ? { ...region, box } : region;
  });
  return { ...doc, regions };
}


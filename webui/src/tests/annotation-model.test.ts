import { describe, expect, it } from "vitest";

import {
  BRUSH_SIZES,
  MAX_REGIONS,
  moveRegion,
  regionLabel,
  resizeBox,
  SCHEMA,
  addRegion,
  boxFromCorners,
  commit,
  createHistory,
  emptyDoc,
  redo,
  removeRegion,
  setNote,
  toPayload,
  undo,
} from "@/components/image/annotation-model";

describe("annotation model", () => {
  it("numbers regions in creation order and does not reuse a number after removal", () => {
    let doc = emptyDoc();
    doc = addRegion(doc, { shape: "rect", box: [0.1, 0.1, 0.2, 0.2] });
    doc = addRegion(doc, { shape: "pin", point: [0.5, 0.5] });
    doc = removeRegion(doc, 1);
    doc = addRegion(doc, { shape: "ellipse", box: [0.3, 0.3, 0.4, 0.4] });
    expect(doc.regions.map((region) => region.id)).toEqual([2, 3]);
  });

  it("stops at the server's region limit", () => {
    let doc = emptyDoc();
    for (let i = 0; i < MAX_REGIONS; i += 1) doc = addRegion(doc, { shape: "pin", point: [0.1, 0.1] });
    expect(addRegion(doc, { shape: "pin", point: [0.2, 0.2] })).toBe(doc);
  });

  it("undoes and redoes whole changes, and a new change clears the redo branch", () => {
    let history = createHistory();
    history = commit(history, addRegion(history.present, { shape: "pin", point: [0.1, 0.1] }));
    history = commit(history, addRegion(history.present, { shape: "pin", point: [0.2, 0.2] }));
    expect(history.present.regions).toHaveLength(2);

    history = undo(history);
    expect(history.present.regions).toHaveLength(1);
    history = redo(history);
    expect(history.present.regions).toHaveLength(2);

    history = undo(history);
    history = commit(history, setNote(history.present, 1, "new branch"));
    expect(history.future).toEqual([]);
  });

  it("does not record a change that did nothing", () => {
    const history = createHistory();
    expect(commit(history, history.present)).toBe(history);
  });

  it("sorts corners, clamps to the image, and drops boxes too small to see", () => {
    expect(boxFromCorners([0.8, 0.9], [0.2, 0.1])).toEqual([0.2, 0.1, 0.8, 0.9]);
    expect(boxFromCorners([-0.2, 0.1], [0.5, 1.4])).toEqual([0, 0.1, 0.5, 1]);
    expect(boxFromCorners([0.5, 0.5], [0.501, 0.9])).toBeNull();
  });

  it("builds the payload the server validates: schema, image, and one edit per region", () => {
    let doc = emptyDoc();
    doc = addRegion(doc, { shape: "rect", box: [0.1, 0.2, 0.3, 0.4], note: "logo" });
    doc = addRegion(doc, { shape: "brush", points: [[0.5, 0.5]], radius: 0.02, note: "remove" });
    doc = addRegion(doc, { shape: "pin", point: [0.9, 0.9], note: "add text" });
    const payload = toPayload({ ...doc, globalNote: "keep colours" }, "assets/banner.png", null);

    expect(payload.schema).toBe(SCHEMA);
    expect(payload.image).toBe("assets/banner.png");
    expect(payload.composite_to_original).toBe(true);
    expect(payload.global_note).toBe("keep colours");
    expect(payload.edits).toEqual([
      { id: 1, shape: "rect", note: "logo", box: [0.1, 0.2, 0.3, 0.4] },
      { id: 2, shape: "brush", note: "remove", points: [[0.5, 0.5]], radius: 0.02 },
      { id: 3, shape: "pin", note: "add text", point: [0.9, 0.9] },
    ]);
  });

  it("clips notes to the server's length", () => {
    const doc = setNote(addRegion(emptyDoc(), { shape: "pin", point: [0.1, 0.1] }), 1, "x".repeat(2_000));
    expect(doc.regions[0].note).toHaveLength(1_000);
  });
});

describe("moving and resizing regions (IM-03)", () => {
  it("moves a box by an offset and keeps its size", () => {
    let doc = addRegion(emptyDoc(), { shape: "rect", box: [0.1, 0.1, 0.3, 0.3] });
    doc = moveRegion(doc, 1, 0.2, 0.1);
    const [x0, y0, x1, y1] = doc.regions[0].box ?? [];
    expect([x0, y0, x1, y1]).toEqual([expect.closeTo(0.3), expect.closeTo(0.2), expect.closeTo(0.5), expect.closeTo(0.4)]);
  });

  it("keeps a moved box inside the image", () => {
    let doc = addRegion(emptyDoc(), { shape: "ellipse", box: [0.1, 0.1, 0.3, 0.3] });
    doc = moveRegion(doc, 1, -0.5, 0.9);
    // The vertical move is clamped by the bottom edge: the box ends exactly at 1.
    const [x0, y0, x1, y1] = doc.regions[0].box ?? [];
    expect(x0).toBeCloseTo(0);
    expect(y0).toBeCloseTo(0.8);
    expect(x1).toBeCloseTo(0.2);
    expect(y1).toBeCloseTo(1);
  });

  it("moves a pin and clamps it to the image", () => {
    let doc = addRegion(emptyDoc(), { shape: "pin", point: [0.5, 0.5] });
    doc = moveRegion(doc, 1, 0.9, -0.9);
    expect(doc.regions[0].point).toEqual([1, 0]);
  });

  it("moves a brush stroke as a whole without letting any point leave the image", () => {
    let doc = addRegion(emptyDoc(), { shape: "brush", points: [[0.2, 0.2], [0.4, 0.5]], radius: 0.02 });
    doc = moveRegion(doc, 1, 1, 0);
    // Moving right stops when the rightmost point reaches the edge.
    expect(doc.regions[0].points).toEqual([[0.8, 0.2], [1, 0.5]]);
  });

  it("resizes from a corner and keeps the opposite corner where it is", () => {
    const doc = addRegion(emptyDoc(), { shape: "rect", box: [0.2, 0.2, 0.6, 0.6] });
    expect(resizeBox(doc, 1, 0, [0.1, 0.1]).regions[0].box).toEqual([0.1, 0.1, 0.6, 0.6]);
    expect(resizeBox(doc, 1, 2, [0.7, 0.7]).regions[0].box).toEqual([0.2, 0.2, 0.7, 0.7]);
  });

  it("ignores a resize that would make the box too small", () => {
    const doc = addRegion(emptyDoc(), { shape: "rect", box: [0.2, 0.2, 0.6, 0.6] });
    expect(resizeBox(doc, 1, 0, [0.599, 0.599]).regions[0].box).toEqual([0.2, 0.2, 0.6, 0.6]);
  });
});

describe("eraser strokes and brush sizes (IM-04)", () => {
  it("marks an eraser stroke in the payload and only then", () => {
    let doc = emptyDoc();
    doc = addRegion(doc, { shape: "brush", points: [[0.5, 0.5]], radius: 0.02 });
    doc = addRegion(doc, { shape: "brush", points: [[0.4, 0.4]], radius: 0.02, erase: true });
    const edits = toPayload(doc, "a.png", null).edits;
    expect(edits[0]).not.toHaveProperty("erase");
    expect(edits[1]).toMatchObject({ erase: true });
    expect(regionLabel(doc.regions[1])).toBe("2 · eraser");
  });

  it("offers three brush sizes with the middle one as the default", () => {
    expect(Object.keys(BRUSH_SIZES)).toEqual(["S", "M", "L"]);
    expect(BRUSH_SIZES.S).toBeLessThan(BRUSH_SIZES.M);
    expect(BRUSH_SIZES.M).toBeLessThan(BRUSH_SIZES.L);
  });
});


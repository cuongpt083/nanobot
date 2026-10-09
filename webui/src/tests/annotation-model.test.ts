import { describe, expect, it } from "vitest";

import {
  MAX_REGIONS,
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

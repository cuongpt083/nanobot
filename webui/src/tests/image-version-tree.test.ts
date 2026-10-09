import { beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  listWorkspaceDir: vi.fn(),
  readWorkspaceFile: vi.fn(),
}));

vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  ...api,
}));

import { familyOf, loadVersionTree, orderVersionTree } from "@/components/image/image-version-tree";

beforeEach(() => {
  vi.clearAllMocks();
});

describe("familyOf", () => {
  it("drops the version number and keeps the folder", () => {
    expect(familyOf("assets/banner.v3.png")).toEqual({ folder: "assets", family: "banner" });
    expect(familyOf("banner.png")).toEqual({ folder: "", family: "banner" });
  });
});

describe("orderVersionTree", () => {
  it("puts each version under the image it was made from, depth first", () => {
    const rows = orderVersionTree([
      { path: "a/banner.v2.png", label: "v2", parent: "a/banner.v1.png" },
      { path: "a/banner.png", label: "original", parent: null },
      { path: "a/banner.v1.png", label: "v1", parent: "a/banner.png" },
      { path: "a/banner.v3.png", label: "v3", parent: "a/banner.png" },
    ]);
    expect(rows.map((row) => [row.label, row.depth])).toEqual([
      ["original", 0], ["v1", 1], ["v2", 2], ["v3", 1],
    ]);
  });

  it("keeps a version whose parent is missing at the top, and survives a cycle", () => {
    const rows = orderVersionTree([
      { path: "a/x.v1.png", label: "v1", parent: "a/gone.png" },
      { path: "a/y.v1.png", label: "v1", parent: "a/z.v1.png" },
      { path: "a/z.v1.png", label: "v1", parent: "a/y.v1.png" },
    ]);
    expect(rows.map((row) => row.path).sort()).toEqual(["a/x.v1.png", "a/y.v1.png", "a/z.v1.png"]);
  });
});

describe("loadVersionTree", () => {
  it("reads the family from the folder and each version's recorded parent", async () => {
    api.listWorkspaceDir.mockResolvedValue({
      path: "assets",
      entries: [
        { name: "banner.png", kind: "file", size: 1 },
        { name: "banner.v1.png", kind: "file", size: 1 },
        { name: "banner.v2.png", kind: "file", size: 1 },
        { name: "banner.v2.annotations.json", kind: "file", size: 1 },
        { name: "other.png", kind: "file", size: 1 },
        { name: "sub", kind: "dir", size: null },
      ],
      truncated: false,
    });
    api.readWorkspaceFile.mockImplementation(async (_token: string, _key: string, path: string) => {
      if (path !== "assets/banner.v2.annotations.json") throw new Error("not found");
      return { path, content: JSON.stringify({ image: "assets/banner.v1.png" }), version: "sha256:x", size: 1 };
    });

    const rows = await loadVersionTree("t", "websocket:a", "assets/banner.v1.png");

    expect(api.listWorkspaceDir).toHaveBeenCalledWith("t", "websocket:a", "assets", "");
    expect(rows.map((row) => [row.path, row.depth])).toEqual([
      ["assets/banner.png", 0],
      ["assets/banner.v1.png", 1],
      ["assets/banner.v2.png", 2],
    ]);
  });

  it("gives no tree when the folder cannot be listed", async () => {
    api.listWorkspaceDir.mockRejectedValue(new Error("nope"));
    expect(await loadVersionTree("t", "websocket:a", "assets/banner.png")).toEqual([]);
  });
});

import { describe, expect, it } from "vitest";

import { MAX_HUNK_CELLS, assemble, diffHunks } from "@/components/workspace/hunks";

const ORIGINAL = ["one", "two", "three", "four", "five", "six"].join("\n");
const PROPOSED = ["one", "TWO", "three", "four", "FIVE", "six", "seven"].join("\n");

describe("diffHunks", () => {
  it("splits separate changes into separate hunks", () => {
    const hunks = diffHunks(ORIGINAL, PROPOSED);
    expect(hunks.map((h) => [h.start, h.oldLines, h.newLines])).toEqual([
      [1, ["two"], ["TWO"]],
      [4, ["five"], ["FIVE"]],
      [6, [], ["seven"]],
    ]);
  });

  it("finds nothing when the texts are equal", () => {
    expect(diffHunks(ORIGINAL, ORIGINAL)).toEqual([]);
  });

  it("does not split a file too large for the table", () => {
    const big = Array.from({ length: 3000 }, (_, i) => `line ${i}`).join("\n");
    expect(3001 * 3001).toBeGreaterThan(MAX_HUNK_CELLS);
    expect(diffHunks(big, `${big}\nmore`)).toEqual([]);
  });
});

describe("assemble", () => {
  it("accepting every hunk gives the proposal, and none gives the original", () => {
    const hunks = diffHunks(ORIGINAL, PROPOSED);
    const all = new Set(hunks.map((h) => h.id));
    expect(assemble(ORIGINAL, hunks, all)).toBe(PROPOSED);
    expect(assemble(ORIGINAL, hunks, new Set())).toBe(ORIGINAL);
  });

  it("accepting one hunk leaves the other as it was", () => {
    const hunks = diffHunks(ORIGINAL, PROPOSED);
    const first = hunks[0].id;
    expect(assemble(ORIGINAL, hunks, new Set([first]))).toBe(
      ["one", "TWO", "three", "four", "five", "six"].join("\n"),
    );
    const second = hunks[1].id;
    expect(assemble(ORIGINAL, hunks, new Set([second]))).toBe(
      ["one", "two", "three", "four", "FIVE", "six"].join("\n"),
    );
  });

  it("keeps the exact text, including a trailing newline", () => {
    const original = "a\nb\n";
    const proposed = "a\nc\n";
    const hunks = diffHunks(original, proposed);
    expect(assemble(original, hunks, new Set(hunks.map((h) => h.id)))).toBe(proposed);
  });
});

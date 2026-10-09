import { describe, expect, it } from "vitest";

import { applyFileMention, fileMentionAt, filterEntries } from "@/lib/file-mention";

describe("fileMentionAt", () => {
  it("reads a path typed after @, with the folder and the prefix", () => {
    const value = "see @notes/pl";
    expect(fileMentionAt(value, value.length)).toEqual({ folder: "notes", prefix: "pl", start: 4, end: 13 });
  });

  it("reads a file name at the project root when it has a dot", () => {
    const value = "@plan.m";
    expect(fileMentionAt(value, value.length)).toEqual({ folder: "", prefix: "plan.m", start: 0, end: 7 });
  });

  it("does not open for a bare @, which belongs to the app and session mentions", () => {
    expect(fileMentionAt("hi @", 4)).toBeNull();
    expect(fileMentionAt("hi @fo", 6)).toBeNull();
  });

  it("does not open when the caret is not at the end of the token", () => {
    const value = "@notes/plan.md tail";
    expect(fileMentionAt(value, 6)).toBeNull();
  });
});

describe("applyFileMention", () => {
  it("replaces the token with the chosen file and a space", () => {
    const value = "see @notes/pl";
    const query = fileMentionAt(value, value.length)!;
    expect(applyFileMention(value, query, "notes/plan.md", false)).toEqual({
      value: "see @notes/plan.md ",
      cursor: 19,
    });
  });

  it("keeps the slash after a folder so the menu opens inside it", () => {
    const value = "@no";
    const query = fileMentionAt("@notes/", 7)!;
    expect(query).toMatchObject({ folder: "notes", prefix: "" });
    expect(applyFileMention("@notes/", query, "notes/archive", true)).toEqual({
      value: "@notes/archive/",
      cursor: 15,
    });
    expect(value).toBe("@no");
  });
});

describe("filterEntries", () => {
  const entries = [
    { name: "plan.md", kind: "file" },
    { name: "archive", kind: "dir" },
    { name: "Plan-notes.txt", kind: "file" },
    { name: ".hidden", kind: "file" },
  ];

  it("keeps names that start with the prefix, ignoring case, folders first", () => {
    expect(filterEntries(entries, "pl").map((e) => e.name)).toEqual(["Plan-notes.txt", "plan.md"]);
    expect(filterEntries(entries, "").map((e) => e.name)).toEqual(["archive", "Plan-notes.txt", "plan.md"]);
  });

  it("hides dot files unless the prefix starts with a dot", () => {
    expect(filterEntries(entries, "").map((e) => e.name)).not.toContain(".hidden");
    expect(filterEntries(entries, ".").map((e) => e.name)).toEqual([".hidden"]);
  });
});

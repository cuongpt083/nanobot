import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import {
  CoworkerMessageCard,
  parseCodingMeta,
  parseCoworkerMessage,
} from "@/components/coworker/CoworkerMessageCard";

const FENCE = "```";

/** The text `CodingRunner._format_delivery_message` produces for an in-place task. */
function directResult(files: string[] = ["+ made.txt", "~ notes.md"]): string {
  return [
    "[auto-coding-result] Task `ct-abc123` (pi) finished with status: `succeeded`",
    "**Goal**: tidy the notes",
    "**Harness Summary**: done",
    "**Changes**: 1 added, 1 modified, 0 deleted (edited in place in `/work/docs`, no branch)",
    "**Tokens**: 120 tokens",
    "**Acceptance**: None configured",
    "**Files**:",
    FENCE,
    ...files,
    FENCE,
    "",
    "The changes are already applied. Review them, then tell the user they can keep them or run `/code discard ct-abc123` to undo them.",
  ].join("\n");
}

const WORKTREE_RESULT = [
  "[auto-coding-result] Task `ct-def456` (agy) finished with status: `succeeded`",
  "**Goal**: fix the bug",
  "**Commits**: 2 commit(s) on `coworker/code/ct-def456`",
  "**Diffstat**:",
  FENCE,
  " a.py | 4 ++--",
  " 1 file changed, 3 insertions(+), 1 deletion(-)",
  FENCE,
  "",
  "Review the results above, then tell the user to `/code merge ct-def456` or `/code discard ct-def456`.",
].join("\n");

describe("parseCodingMeta for in-place tasks", () => {
  it("reads the mode, the counts and the changed files", () => {
    const meta = parseCodingMeta(directResult());
    expect(meta.mode).toBe("direct");
    expect(meta.backend).toBe("pi");
    expect(meta.changes).toEqual({ added: 1, modified: 1, deleted: 0 });
    expect(meta.files).toEqual([
      { mark: "+", path: "made.txt" },
      { mark: "~", path: "notes.md" },
    ]);
    expect(meta.added).toBeUndefined();
  });

  it("leaves worktree results exactly as before", () => {
    const meta = parseCodingMeta(WORKTREE_RESULT);
    expect(meta.mode).toBeUndefined();
    expect(meta.files).toBeUndefined();
    expect(meta.added).toBe(3);
    expect(meta.removed).toBe(1);
  });

  it("ignores a files block it cannot read", () => {
    const meta = parseCodingMeta(directResult(["not a change line"]));
    expect(meta.mode).toBe("direct");
    expect(meta.files).toEqual([]);
  });
});

describe("coding result card for in-place tasks", () => {
  function renderCard(text: string) {
    const data = parseCoworkerMessage(text);
    expect(data).not.toBeNull();
    render(<CoworkerMessageCard data={data!} />);
  }

  it("badges the task as in place and lists the files instead of line counts", () => {
    renderCard(directResult());
    expect(screen.getByTestId("coding-mode")).toHaveTextContent("In place");
    expect(screen.getByTestId("coding-changes")).toHaveTextContent("+1 ~1 −0");
    expect(screen.queryByTestId("coding-lines")).not.toBeInTheDocument();
    const files = screen.getByTestId("coding-files");
    expect(within(files).getByText("made.txt", { exact: false })).toBeInTheDocument();
    expect(within(files).getByText("notes.md", { exact: false })).toBeInTheDocument();
  });

  it("shortens a long file list", () => {
    const many = Array.from({ length: 7 }, (_, i) => `~ f${i}.md`);
    renderCard(directResult(many));
    const items = within(screen.getByTestId("coding-files")).getAllByRole("listitem");
    expect(items).toHaveLength(5); // four files and the "… and 3 more" line
    expect(items[4]).toHaveTextContent("and 3 more");
  });

  it("keeps the git card as it was", () => {
    renderCard(WORKTREE_RESULT);
    expect(screen.queryByTestId("coding-mode")).not.toBeInTheDocument();
    expect(screen.queryByTestId("coding-files")).not.toBeInTheDocument();
    expect(screen.getByTestId("coding-lines")).toHaveTextContent("+3 −1");
  });

  it("shows the whole result when expanded", () => {
    renderCard(directResult());
    fireEvent.click(screen.getByRole("button"));
    expect(screen.getByText(/The changes are already applied/)).toBeInTheDocument();
  });
});

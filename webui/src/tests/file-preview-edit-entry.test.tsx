import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { FilePreviewPanel } from "@/components/FilePreviewPanel";
import type { FilePreviewPayload } from "@/lib/types";

vi.mock("@/components/workspace/WorkspaceEditor", () => ({
  WorkspaceEditor: () => <div data-testid="editor-stub" />,
}));

const textPreview: FilePreviewPayload = {
  kind: "text",
  path: "/proj/notes.md",
  display_path: "notes.md",
  project_path: "/proj",
  size: 7,
  language: "markdown",
  content: "# Hi\n",
  truncated: false,
} as FilePreviewPayload;

describe("FilePreviewPanel edit entry", () => {
  it("offers Edit for a text file when a mutation transport is available", () => {
    render(
      <FilePreviewPanel
        sessionKey="websocket:abc"
        path="notes.md"
        token="t"
        client={{ requestMutation: vi.fn() } as never}
        initialPreview={textPreview}
      />,
    );
    expect(screen.getByRole("button", { name: "Edit" })).toBeInTheDocument();
  });

  it("stays read-only without a transport", () => {
    render(<FilePreviewPanel sessionKey="websocket:abc" path="notes.md" token="t" initialPreview={textPreview} />);
    expect(screen.queryByRole("button", { name: "Edit" })).toBeNull();
  });
});

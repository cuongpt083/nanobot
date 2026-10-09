import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  listWorkspaceDir: vi.fn(),
  readWorkspaceFile: vi.fn(),
  listStagedChanges: vi.fn(),
  setWorkspaceOpenTabs: vi.fn(),
}));

vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  ...api,
}));

// Monaco does not lay out in happy-dom. The stub exposes the two events the editor reports (a selection and
// the ask-agent action) as buttons, so the editor's own handling is what gets tested.
vi.mock("@/components/workspace/MonacoEditor", () => ({
  MonacoEditor: ({
    value,
    onSelectionChange,
    onAskAgent,
  }: {
    value: string;
    onSelectionChange?: (selection: { text: string; startLine: number; endLine: number } | null) => void;
    onAskAgent?: (selection: { text: string; startLine: number; endLine: number }) => void;
  }) => (
    <div>
      <textarea aria-label="editor" value={value} onChange={() => undefined} />
      <button type="button" onClick={() => onSelectionChange?.({ text: "picked", startLine: 2, endLine: 3 })}>select</button>
      <button type="button" onClick={() => onSelectionChange?.(null)}>clear selection</button>
      <button type="button" onClick={() => onAskAgent?.({ text: "picked", startLine: 2, endLine: 3 })}>ask</button>
    </div>
  ),
}));

vi.mock("@/components/MarkdownText", () => ({
  MarkdownText: ({ children }: { children: string }) => <div>{children}</div>,
}));

import { CHANGES_POLL_MS, WorkspaceEditor } from "@/components/workspace/WorkspaceEditor";
import { readSharedEditorContext, setEditorContextShared } from "@/lib/editor-context";
import type { StagedChange } from "@/lib/api";

const client = { requestMutation: vi.fn() } as never;

function proposal(path: string): StagedChange {
  return {
    id: "c1", path, content: "new", base_version: "sha256:v1", proposed_version: "sha256:v2",
    by: "sales-writer", created_at: 1, stale: false, current_version: "sha256:v1",
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  setEditorContextShared(false);
  api.listWorkspaceDir.mockResolvedValue({ path: "", entries: [{ name: "notes.md", kind: "file", size: 3 }], truncated: false });
  api.readWorkspaceFile.mockResolvedValue({ path: "notes.md", content: "one\ntwo\nthree", version: "sha256:v1", size: 13 });
  api.listStagedChanges.mockResolvedValue([]);
  api.setWorkspaceOpenTabs.mockResolvedValue(undefined);
});

afterEach(() => {
  vi.useRealTimers();
  try {
    globalThis.localStorage?.removeItem("nanobot.shareEditorContext");
  } catch {
    // storage unavailable in this environment
  }
});

function renderEditor(onAskAgent?: (quote: string) => void) {
  return render(
    <WorkspaceEditor sessionKey="websocket:abc" token="t" client={client} initialPath="notes.md" onAskAgent={onAskAgent} />,
  );
}

describe("ask the agent about a selection (ED-12)", () => {
  it("sends the picked text with its file and line range to the composer", async () => {
    const onAskAgent = vi.fn();
    renderEditor(onAskAgent);
    await screen.findByLabelText("editor");

    fireEvent.click(screen.getByRole("button", { name: "ask" }));
    expect(onAskAgent).toHaveBeenCalledWith("From notes.md, lines 2-3:\npicked");
  });
});

describe("share the open file with the agent (ED-14)", () => {
  it("is off by default and publishes nothing for the session", async () => {
    renderEditor();
    await screen.findByLabelText("editor");
    fireEvent.click(screen.getByRole("button", { name: "select" }));
    expect(readSharedEditorContext("websocket:abc")).toBeNull();
  });

  it("shares the file and the selection once the user opts in, only for that session", async () => {
    renderEditor();
    await screen.findByLabelText("editor");

    fireEvent.click(screen.getByLabelText("Share with agent"));
    fireEvent.click(screen.getByRole("button", { name: "select" }));

    expect(readSharedEditorContext("websocket:abc")).toEqual({
      path: "notes.md", start_line: 2, end_line: 3, selection: "picked",
    });
    expect(readSharedEditorContext("websocket:other")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "clear selection" }));
    expect(readSharedEditorContext("websocket:abc")).toEqual({ path: "notes.md" });
  });

  it("stops sharing when the editor closes", async () => {
    const { unmount } = renderEditor();
    await screen.findByLabelText("editor");
    fireEvent.click(screen.getByLabelText("Share with agent"));
    expect(readSharedEditorContext("websocket:abc")).toEqual({ path: "notes.md" });

    unmount();
    expect(readSharedEditorContext("websocket:abc")).toBeNull();
  });

  it("remembers the choice in this browser", async () => {
    setEditorContextShared(true);
    renderEditor();
    expect(await screen.findByLabelText("Share with agent")).toBeChecked();
  });
});

describe("proposals on open files (ED-15)", () => {
  it("marks the tab of a file the agent has a pending proposal for", async () => {
    api.listStagedChanges.mockResolvedValue([proposal("notes.md")]);
    renderEditor();
    await screen.findByLabelText("editor");

    expect(await screen.findByRole("img", { name: "The agent proposed a change to this file" })).toBeInTheDocument();
  });

  it("shows a new proposal without reloading the editor", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    renderEditor();
    await screen.findByLabelText("editor");
    expect(screen.queryByRole("img", { name: "The agent proposed a change to this file" })).toBeNull();

    api.listStagedChanges.mockResolvedValue([proposal("notes.md")]);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(CHANGES_POLL_MS + 10);
    });
    await waitFor(() =>
      expect(screen.getByRole("img", { name: "The agent proposed a change to this file" })).toBeInTheDocument(),
    );
  });
});

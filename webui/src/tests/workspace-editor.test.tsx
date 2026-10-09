import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  listWorkspaceDir: vi.fn(),
  readWorkspaceFile: vi.fn(),
  saveWorkspaceFile: vi.fn(),
  renameWorkspaceFile: vi.fn(),
  deleteWorkspaceFile: vi.fn(),
  listStagedChanges: vi.fn(),
  setWorkspaceOpenTabs: vi.fn(),
}));

vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  ...api,
}));

// Monaco itself does not lay out in happy-dom; a textarea with the same props is enough to test the editor logic.
vi.mock("@/components/workspace/MonacoEditor", () => ({
  MonacoEditor: ({ value, onChange, onSave }: { value: string; onChange: (t: string) => void; onSave: () => void }) => (
    <textarea
      aria-label="editor"
      value={value}
      onChange={(event) => onChange(event.target.value)}
      onKeyDown={(event) => {
        if ((event.ctrlKey || event.metaKey) && event.key === "s") onSave();
      }}
    />
  ),
}));

vi.mock("@/components/MarkdownText", () => ({
  MarkdownText: ({ children }: { children: string }) => <div data-testid="preview">{children}</div>,
}));

import { ApiError } from "@/lib/api";
import { WorkspaceEditor } from "@/components/workspace/WorkspaceEditor";

const client = { requestMutation: vi.fn() } as never;

function file(path: string, content: string, version: string) {
  return { path, content, version, size: content.length };
}

beforeEach(() => {
  vi.clearAllMocks();
  api.listStagedChanges.mockResolvedValue([]);
  api.setWorkspaceOpenTabs.mockResolvedValue(undefined);
  api.listWorkspaceDir.mockResolvedValue({
    path: "",
    entries: [
      { name: "docs", kind: "dir", size: null },
      { name: "notes.md", kind: "file", size: 12 },
    ],
    truncated: false,
  });
});

afterEach(() => {
  vi.useRealTimers();
});

function renderEditor(initialPath = "notes.md") {
  return render(<WorkspaceEditor sessionKey="websocket:abc" token="t" client={client} initialPath={initialPath} />);
}

describe("WorkspaceEditor", () => {
  it("opens the requested file in the editor", async () => {
    api.readWorkspaceFile.mockResolvedValue(file("notes.md", "# Hello", "sha256:aaa"));
    renderEditor();

    const editor = await screen.findByLabelText("editor");
    expect(editor).toHaveValue("# Hello");
    expect(api.readWorkspaceFile).toHaveBeenCalledWith("t", "websocket:abc", "notes.md", "");
  });

  it("tracks unsaved changes and saves against the version it opened", async () => {
    api.readWorkspaceFile.mockResolvedValue(file("notes.md", "one", "sha256:v1"));
    api.saveWorkspaceFile.mockResolvedValue({ path: "notes.md", version: "sha256:v2", size: 3 });
    renderEditor();

    const editor = await screen.findByLabelText("editor");
    fireEvent.change(editor, { target: { value: "two" } });
    expect(screen.getByText("Unsaved")).toBeInTheDocument();

    fireEvent.keyDown(editor, { key: "s", ctrlKey: true });
    await waitFor(() => expect(api.saveWorkspaceFile).toHaveBeenCalledTimes(1));
    expect(api.saveWorkspaceFile).toHaveBeenCalledWith(client, "websocket:abc", {
      path: "notes.md",
      content: "two",
      baseVersion: "sha256:v1",
    });
    await waitFor(() => expect(screen.getByText("Saved")).toBeInTheDocument());

    // The next save is based on the version the server just returned.
    fireEvent.change(editor, { target: { value: "three" } });
    fireEvent.keyDown(editor, { key: "s", ctrlKey: true });
    await waitFor(() => expect(api.saveWorkspaceFile).toHaveBeenCalledTimes(2));
    expect(api.saveWorkspaceFile.mock.calls[1][2].baseVersion).toBe("sha256:v2");
  });

  it("reports a conflict instead of overwriting, and lets the user reload from disk", async () => {
    api.readWorkspaceFile
      .mockResolvedValueOnce(file("notes.md", "mine?", "sha256:v1"))
      .mockResolvedValueOnce(file("notes.md", "theirs", "sha256:v9"));
    api.saveWorkspaceFile.mockRejectedValueOnce(new ApiError(409, "file changed since it was opened"));
    renderEditor();

    const editor = await screen.findByLabelText("editor");
    fireEvent.change(editor, { target: { value: "mine" } });
    fireEvent.keyDown(editor, { key: "s", ctrlKey: true });

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("changed on disk");
    fireEvent.click(screen.getByRole("button", { name: "Reload from disk" }));

    await waitFor(() => expect(screen.getByLabelText("editor")).toHaveValue("theirs"));
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("keeps the user's text on a conflict when they choose to keep it", async () => {
    api.readWorkspaceFile
      .mockResolvedValueOnce(file("notes.md", "base", "sha256:v1"))
      .mockResolvedValueOnce(file("notes.md", "theirs", "sha256:v9"));
    api.saveWorkspaceFile
      .mockRejectedValueOnce(new ApiError(409, "conflict"))
      .mockResolvedValueOnce({ path: "notes.md", version: "sha256:v10", size: 4 });
    renderEditor();

    const editor = await screen.findByLabelText("editor");
    fireEvent.change(editor, { target: { value: "mine" } });
    fireEvent.keyDown(editor, { key: "s", ctrlKey: true });
    await screen.findByRole("alert");

    fireEvent.click(screen.getByRole("button", { name: "Keep my version" }));
    await waitFor(() => expect(api.saveWorkspaceFile).toHaveBeenCalledTimes(2));
    // The retry is based on the freshly read version, and carries the user's text.
    expect(api.saveWorkspaceFile.mock.calls[1][2]).toEqual({
      path: "notes.md",
      content: "mine",
      baseVersion: "sha256:v9",
    });
    expect(screen.getByLabelText("editor")).toHaveValue("mine");
  });

  it("shows a markdown preview that follows the text after a short pause", async () => {
    api.readWorkspaceFile.mockResolvedValue(file("notes.md", "# Title", "sha256:v1"));
    renderEditor();

    const editor = await screen.findByLabelText("editor");
    expect(screen.getByTestId("preview")).toHaveTextContent("# Title");
    fireEvent.change(editor, { target: { value: "# Changed" } });
    expect(screen.getByTestId("preview")).toHaveTextContent("# Title"); // not yet: debounced
    await waitFor(() => expect(screen.getByTestId("preview")).toHaveTextContent("# Changed"), { timeout: 1500 });
  });

  it("has no preview for a non-markdown file", async () => {
    api.readWorkspaceFile.mockResolvedValue(file("app.py", "print(1)", "sha256:v1"));
    renderEditor("app.py");

    await screen.findByLabelText("editor");
    expect(screen.queryByTestId("preview")).toBeNull();
  });

  it("opens a file from the tree, including one inside a folder", async () => {
    api.readWorkspaceFile
      .mockResolvedValueOnce(file("notes.md", "first", "sha256:v1"))
      .mockResolvedValueOnce(file("docs/todo.txt", "second", "sha256:v2"));
    api.listWorkspaceDir.mockImplementation(async (_token: string, _key: string, folder: string) =>
      folder === "docs"
        ? { path: "docs", entries: [{ name: "todo.txt", kind: "file", size: 6 }], truncated: false }
        : {
          path: "",
          entries: [{ name: "docs", kind: "dir", size: null }, { name: "notes.md", kind: "file", size: 5 }],
          truncated: false,
        },
    );
    renderEditor();
    await screen.findByLabelText("editor");

    fireEvent.click(await screen.findByRole("button", { name: "docs" }));
    fireEvent.click(await screen.findByRole("button", { name: "todo.txt" }));

    await waitFor(() => expect(screen.getByLabelText("editor")).toHaveValue("second"));
    expect(api.readWorkspaceFile).toHaveBeenLastCalledWith("t", "websocket:abc", "docs/todo.txt", "");
  });
});

describe("WorkspaceEditor tab close", () => {
  it("asks before closing a tab with unsaved changes", async () => {
    api.readWorkspaceFile.mockResolvedValue(file("notes.md", "x", "sha256:v1"));
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    renderEditor();

    const editor = await screen.findByLabelText("editor");
    fireEvent.change(editor, { target: { value: "dirty" } });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Close notes.md" }));
    });
    expect(confirm).toHaveBeenCalled();
    expect(screen.getByLabelText("editor")).toHaveValue("dirty"); // the tab stayed open
    confirm.mockRestore();
  });
});

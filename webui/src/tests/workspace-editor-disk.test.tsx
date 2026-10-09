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

vi.mock("@/components/workspace/MonacoEditor", () => ({
  MonacoEditor: ({ value, onChange }: { value: string; onChange: (t: string) => void }) => (
    <textarea aria-label="editor" value={value} onChange={(event) => onChange(event.target.value)} />
  ),
}));

vi.mock("@/components/MarkdownText", () => ({
  MarkdownText: ({ children }: { children: string }) => <div>{children}</div>,
}));

import { DISK_POLL_MS, WorkspaceEditor } from "@/components/workspace/WorkspaceEditor";

const client = { requestMutation: vi.fn() } as never;

/** The disk, as the gateway would report it: text and version per path. Tests change it between polls. */
let disk: Record<string, { content: string; version: string }> = {};

beforeEach(() => {
  vi.clearAllMocks();
  vi.useFakeTimers({ shouldAdvanceTime: true });
  disk = {
    "notes.md": { content: "one", version: "sha256:v1" },
    "other.md": { content: "other", version: "sha256:o1" },
  };
  api.listWorkspaceDir.mockResolvedValue({
    path: "",
    entries: [{ name: "notes.md", kind: "file", size: 3 }, { name: "other.md", kind: "file", size: 5 }],
    truncated: false,
  });
  api.readWorkspaceFile.mockImplementation(async (_token: string, _key: string, path: string) => {
    const file = disk[path];
    if (!file) throw new Error("missing");
    return { path, content: file.content, version: file.version, size: file.content.length };
  });
  api.listStagedChanges.mockResolvedValue([]);
  api.setWorkspaceOpenTabs.mockResolvedValue(undefined);
});

afterEach(() => {
  vi.useRealTimers();
});

async function advancePoll() {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(DISK_POLL_MS + 10);
  });
}

function renderEditor() {
  return render(<WorkspaceEditor sessionKey="websocket:abc" token="t" client={client} initialPath="notes.md" />);
}

describe("files changed on disk while open (ED-15)", () => {
  it("a clean tab takes the new text from disk", async () => {
    renderEditor();
    expect(await screen.findByLabelText("editor")).toHaveValue("one");

    disk["notes.md"] = { content: "one, edited elsewhere", version: "sha256:v2" };
    await advancePoll();

    await waitFor(() => expect(screen.getByLabelText("editor")).toHaveValue("one, edited elsewhere"));
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("a tab with unsaved text is not replaced; it gets the conflict banner", async () => {
    renderEditor();
    const editor = await screen.findByLabelText("editor");
    fireEvent.change(editor, { target: { value: "my unsaved text" } });

    disk["notes.md"] = { content: "theirs", version: "sha256:v2" };
    await advancePoll();

    expect(await screen.findByRole("alert")).toHaveTextContent("changed on disk");
    expect(screen.getByLabelText("editor")).toHaveValue("my unsaved text");
  });

  it("a background tab that changed is marked until it is opened", async () => {
    renderEditor();
    await screen.findByLabelText("editor");
    fireEvent.click(await screen.findByRole("button", { name: "other.md" }));

    disk["notes.md"] = { content: "two", version: "sha256:v2" };
    await advancePoll();

    const mark = await screen.findByRole("img", { name: "Changed on disk" });
    expect(mark).toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: "notes.md" }));
    await waitFor(() => expect(screen.queryByRole("img", { name: "Changed on disk" })).toBeNull());
  });
});

describe("fs.changed from the gateway (ED-15)", () => {
  it("re-reads a changed open file at once, without waiting for the poll", async () => {
    const { emitWorkspaceChange } = await import("@/lib/workspace-events");
    renderEditor();
    expect(await screen.findByLabelText("editor")).toHaveValue("one");

    disk["notes.md"] = { content: "pushed change", version: "sha256:v9" };
    await act(async () => {
      emitWorkspaceChange({ sessionKey: "websocket:abc", path: "notes.md" });
    });

    await waitFor(() => expect(screen.getByLabelText("editor")).toHaveValue("pushed change"));
  });

  it("ignores a change for another session or a file that is not open", async () => {
    const { emitWorkspaceChange } = await import("@/lib/workspace-events");
    renderEditor();
    await screen.findByLabelText("editor");
    const reads = api.readWorkspaceFile.mock.calls.length;

    await act(async () => {
      emitWorkspaceChange({ sessionKey: "websocket:other", path: "notes.md" });
      emitWorkspaceChange({ sessionKey: "websocket:abc", path: "unopened.md" });
    });

    expect(api.readWorkspaceFile.mock.calls.length).toBe(reads);
  });
});

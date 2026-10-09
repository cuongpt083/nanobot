import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  listWorkspaceDir: vi.fn(),
  readWorkspaceFile: vi.fn(),
  saveWorkspaceFile: vi.fn(),
  renameWorkspaceFile: vi.fn(),
  deleteWorkspaceFile: vi.fn(),
  listStagedChanges: vi.fn(),
  setWorkspaceOpenTabs: vi.fn(),
  resolveStagedChange: vi.fn(),
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

// Monaco's diff editor does not lay out in happy-dom; the review logic is what is under test here.
vi.mock("@/components/workspace/DiffView", () => ({
  DiffView: ({ original, modified }: { original: string; modified: string }) => (
    <pre data-testid="diff">{`${original}\n---\n${modified}`}</pre>
  ),
}));

vi.mock("@/components/MarkdownText", () => ({
  MarkdownText: ({ children }: { children: string }) => <div>{children}</div>,
}));

import { ApiError, type StagedChange } from "@/lib/api";
import { WorkspaceEditor } from "@/components/workspace/WorkspaceEditor";

const client = { requestMutation: vi.fn() } as never;

function change(overrides: Partial<StagedChange> = {}): StagedChange {
  return {
    id: "c1",
    path: "notes.md",
    content: "new text",
    base_version: "sha256:v1",
    proposed_version: "sha256:v2",
    by: "sales-writer",
    created_at: 1,
    stale: false,
    current_version: "sha256:v1",
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  api.listWorkspaceDir.mockResolvedValue({ path: "", entries: [{ name: "notes.md", kind: "file", size: 3 }], truncated: false });
  api.readWorkspaceFile.mockResolvedValue({ path: "notes.md", content: "old text", version: "sha256:v1", size: 8 });
  api.setWorkspaceOpenTabs.mockResolvedValue(undefined);
});

function renderEditor() {
  return render(<WorkspaceEditor sessionKey="websocket:abc" token="t" client={client} initialPath="notes.md" />);
}

describe("staged change review in the editor", () => {
  it("shows how many changes are proposed and opens the review on the change", async () => {
    api.listStagedChanges.mockResolvedValue([change()]);
    renderEditor();
    fireEvent.click(await screen.findByRole("button", { name: "1 proposed change(s)" }));

    const review = await screen.findByTestId("change-review");
    expect(review).toHaveTextContent("notes.md");
    expect(review).toHaveTextContent("sales-writer");
    await waitFor(() => expect(screen.getByTestId("diff")).toHaveTextContent("old text"));
    expect(screen.getByTestId("diff")).toHaveTextContent("new text");
  });

  it("accepts through the gateway and reloads an open clean file from disk", async () => {
    api.listStagedChanges.mockResolvedValueOnce([change()]).mockResolvedValue([]);
    api.resolveStagedChange.mockResolvedValue({ id: "c1", status: "accepted", path: "notes.md" });
    renderEditor();
    fireEvent.click(await screen.findByRole("button", { name: "1 proposed change(s)" }));
    fireEvent.click(await screen.findByRole("button", { name: "Accept" }));

    await waitFor(() => expect(api.readWorkspaceFile).toHaveBeenCalledTimes(2));
    expect(api.resolveStagedChange).toHaveBeenCalledWith(client, "websocket:abc", "c1", "accept");
    expect(api.readWorkspaceFile).toHaveBeenLastCalledWith("t", "websocket:abc", "notes.md", "");
  });

  it("does not offer accept for a change whose file moved on since the agent read it", async () => {
    api.listStagedChanges.mockResolvedValue([change({ stale: true, current_version: "sha256:other" })]);
    renderEditor();
    fireEvent.click(await screen.findByRole("button", { name: "1 proposed change(s)" }));

    expect(await screen.findByRole("button", { name: "Accept" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Reject" })).toBeEnabled();
  });

  it("reports the open tabs to the gateway", async () => {
    renderEditor();
    await screen.findByLabelText("editor");
    await waitFor(() =>
      expect(api.setWorkspaceOpenTabs).toHaveBeenLastCalledWith(client, "websocket:abc", ["notes.md"]),
    );
  });

  it("marks an open dirty file as conflicting when a change to it is accepted", async () => {
    api.listStagedChanges.mockResolvedValueOnce([change()]).mockResolvedValue([]);
    renderEditor();
    const editor = await screen.findByLabelText("editor");
    fireEvent.change(editor, { target: { value: "my unsaved text" } });
    fireEvent.click(await screen.findByRole("button", { name: "1 proposed change(s)" }));
    fireEvent.click(await screen.findByRole("button", { name: "Accept" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("changed on disk");
    expect(screen.getByLabelText("editor")).toHaveValue("my unsaved text"); // not reloaded over the user's text
  });

  it("keeps the review open with a message when accept is refused as stale", async () => {
    api.listStagedChanges.mockResolvedValue([change()]);
    api.resolveStagedChange.mockRejectedValueOnce(new ApiError(409, "stale"));
    renderEditor();
    fireEvent.click(await screen.findByRole("button", { name: "1 proposed change(s)" }));
    fireEvent.click(await screen.findByRole("button", { name: "Accept" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("changed after the agent read it");
    expect(screen.getByTestId("change-review")).toBeInTheDocument();
  });
});

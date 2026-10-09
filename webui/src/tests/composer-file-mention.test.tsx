import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ThreadComposer } from "@/components/thread/ThreadComposer";

const ENTRIES = [
  { name: "plan.md", kind: "file" },
  { name: "archive", kind: "dir" },
];

describe("file suggestions after @ in the composer (ED-13)", () => {
  it("offers project files after @path and inserts the one chosen", async () => {
    const listFolder = vi.fn(async () => ENTRIES);
    render(<ThreadComposer onSend={vi.fn()} listFolder={listFolder} />);
    const textarea = screen.getByLabelText(/message input/i) as HTMLTextAreaElement;

    fireEvent.change(textarea, { target: { value: "see @plan." } });
    textarea.setSelectionRange(10, 10);
    fireEvent.keyUp(textarea, { key: "l" });

    expect(await screen.findByRole("option", { name: "plan.md" })).toBeInTheDocument();
    expect(listFolder).toHaveBeenCalledWith("");

    await act(async () => {
      fireEvent.mouseDown(screen.getByRole("option", { name: "plan.md" }));
    });
    await waitFor(() => expect(textarea.value).toBe("see @plan.md "));
  });

  it("lists the folder typed before the slash, and offers its files", async () => {
    const listFolder = vi.fn(async (folder: string) =>
      folder === "notes" ? [{ name: "deep.md", kind: "file" }] : ENTRIES,
    );
    render(<ThreadComposer onSend={vi.fn()} listFolder={listFolder} />);
    const textarea = screen.getByLabelText(/message input/i) as HTMLTextAreaElement;

    fireEvent.change(textarea, { target: { value: "@notes/" } });
    textarea.setSelectionRange(7, 7);
    fireEvent.keyUp(textarea, { key: "/" });
    const option = await screen.findByRole("option", { name: "notes/deep.md" });
    await act(async () => {
      fireEvent.mouseDown(option);
    });

    await waitFor(() => expect(textarea.value).toBe("@notes/deep.md "));
    expect(listFolder).toHaveBeenCalledWith("notes");
  });

  it("closes on Escape, and a bare @ does not open the file suggestions", async () => {
    const listFolder = vi.fn(async () => ENTRIES);
    render(<ThreadComposer onSend={vi.fn()} listFolder={listFolder} />);
    const textarea = screen.getByLabelText(/message input/i) as HTMLTextAreaElement;

    fireEvent.change(textarea, { target: { value: "@" } });
    textarea.setSelectionRange(1, 1);
    fireEvent.keyUp(textarea, { key: "@" });
    expect(listFolder).not.toHaveBeenCalled();

    fireEvent.change(textarea, { target: { value: "@plan." } });
    textarea.setSelectionRange(6, 6);
    fireEvent.keyUp(textarea, { key: "." });
    await screen.findByRole("option", { name: "plan.md" });
    fireEvent.keyDown(textarea, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("option", { name: "plan.md" })).toBeNull());
  });
});

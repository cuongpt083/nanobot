import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  readWorkspaceFile: vi.fn(),
  saveWorkspaceFile: vi.fn(),
}));

vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  ...api,
}));

// Canvas does not run in happy-dom; the pane's own state and requests are what is under test.
vi.mock("react-konva", async () => {
  const React = await import("react");
  const passthrough = (name: string) => ({ children }: { children?: unknown }) =>
    React.createElement("div", { "data-konva": name }, children as never);
  return {
    Stage: React.forwardRef((props: { children?: unknown }, ref: unknown) => {
      void ref;
      return React.createElement("div", { "data-konva": "Stage" }, props.children as never);
    }),
    Layer: passthrough("Layer"),
    Image: passthrough("Image"),
    Rect: passthrough("Rect"),
    Ellipse: passthrough("Ellipse"),
    Line: passthrough("Line"),
    Circle: passthrough("Circle"),
    Text: passthrough("Text"),
  };
});

import { ImageReviewPane, annotationPathFor, editRequestText } from "@/components/image/ImageReviewPane";
import { ApiError } from "@/lib/api";

const client = { requestMutation: vi.fn() } as never;

class LoadedImage {
  naturalWidth = 400;
  naturalHeight = 300;
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;
  set src(_value: string) {
    queueMicrotask(() => this.onload?.());
  }
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.stubGlobal("Image", LoadedImage);
  vi.stubGlobal("ResizeObserver", class {
    observe() {}
    disconnect() {}
  });
  api.readWorkspaceFile.mockRejectedValue(new ApiError(404, "not found"));
  api.saveWorkspaceFile.mockResolvedValue({ path: "x.annotations.json", version: "sha256:new", size: 10 });
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function renderPane(onSend = vi.fn()) {
  render(
    <ImageReviewPane
      sessionKey="websocket:abc"
      token="t"
      client={client}
      path="assets/banner.png"
      src="data:image/png;base64,AAAA"
      onSend={onSend}
    />,
  );
  return onSend;
}

describe("annotation paths and the request text", () => {
  it("puts the annotation file next to the image", () => {
    expect(annotationPathFor("assets/banner.v3.png")).toBe("assets/banner.v3.annotations.json");
    expect(annotationPathFor("photo")).toBe("photo.annotations.json");
  });

  it("asks for the edit with the image, the annotation file and the skill name", () => {
    const text = editRequestText("assets/banner.png", "assets/banner.annotations.json");
    expect(text).toContain("assets/banner.png");
    expect(text).toContain("assets/banner.annotations.json");
    expect(text).toContain("image-region-edit");
  });
});

describe("ImageReviewPane send", () => {
  it("does not send with nothing marked", async () => {
    renderPane();
    await screen.findByTestId("image-review-pane");
    expect(screen.getByRole("button", { name: "Send edits" })).toBeDisabled();
  });

  it("saves the annotation file as a new file, then asks the agent", async () => {
    const onSend = renderPane();
    await screen.findByTestId("image-review-pane");
    fireEvent.change(screen.getByLabelText("Note for the whole image"), { target: { value: "keep colours" } });
    fireEvent.blur(screen.getByLabelText("Note for the whole image"));
    fireEvent.click(screen.getByRole("button", { name: "Send edits" }));

    await waitFor(() => expect(onSend).toHaveBeenCalledTimes(1));
    expect(api.saveWorkspaceFile).toHaveBeenCalledWith(client, "websocket:abc", expect.objectContaining({
      path: "assets/banner.annotations.json",
      baseVersion: null,
    }));
    const saved = JSON.parse(api.saveWorkspaceFile.mock.calls[0][2].content as string);
    expect(saved.schema).toBe("nanobot.image-annotations/v1");
    expect(saved.global_note).toBe("keep colours");
    expect(onSend).toHaveBeenCalledWith(editRequestText("assets/banner.png", "assets/banner.annotations.json"));
  });

  it("builds on the version of an existing annotation file", async () => {
    api.readWorkspaceFile.mockResolvedValue({ path: "assets/banner.annotations.json", content: "{}", version: "sha256:old", size: 2 });
    renderPane();
    await screen.findByTestId("image-review-pane");
    fireEvent.change(screen.getByLabelText("Note for the whole image"), { target: { value: "again" } });
    fireEvent.blur(screen.getByLabelText("Note for the whole image"));
    fireEvent.click(screen.getByRole("button", { name: "Send edits" }));

    await waitFor(() => expect(api.saveWorkspaceFile).toHaveBeenCalled());
    expect(api.saveWorkspaceFile.mock.calls[0][2].baseVersion).toBe("sha256:old");
  });

  it("does not send when the annotation file changed since it was read, and says so", async () => {
    api.readWorkspaceFile.mockResolvedValue({ path: "x", content: "{}", version: "sha256:old", size: 2 });
    api.saveWorkspaceFile.mockRejectedValueOnce(new ApiError(409, "changed"));
    const onSend = renderPane();
    await screen.findByTestId("image-review-pane");
    fireEvent.change(screen.getByLabelText("Note for the whole image"), { target: { value: "x" } });
    fireEvent.blur(screen.getByLabelText("Note for the whole image"));
    fireEvent.click(screen.getByRole("button", { name: "Send edits" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("changed on disk");
    expect(onSend).not.toHaveBeenCalled();
  });

  it("can undo a note change with the keyboard", async () => {
    renderPane();
    const pane = await screen.findByTestId("image-review-pane");
    fireEvent.change(screen.getByLabelText("Note for the whole image"), { target: { value: "first" } });
    fireEvent.blur(screen.getByLabelText("Note for the whole image"));
    expect(screen.getByLabelText("Note for the whole image")).toHaveValue("first");

    fireEvent.keyDown(pane, { key: "z", ctrlKey: true });
    expect(screen.getByLabelText("Note for the whole image")).toHaveValue("");
  });
});

describe("ImageReviewPane tools (IM-03, IM-04)", () => {
  it("shows the brush sizes for the brush and the eraser, and not for the rectangle", async () => {
    renderPane();
    await screen.findByTestId("image-review-pane");
    expect(screen.queryByRole("group", { name: "Brush size" })).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Brush" }));
    expect(screen.getByRole("group", { name: "Brush size" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "L" }));
    expect(screen.getByRole("button", { name: "L" })).toHaveAttribute("aria-pressed", "true");

    fireEvent.click(screen.getByRole("button", { name: "Eraser" }));
    expect(screen.getByRole("group", { name: "Brush size" })).toBeInTheDocument();
  });

  it("has the eraser and the select tool, and cannot delete when nothing is selected", async () => {
    renderPane();
    await screen.findByTestId("image-review-pane");
    expect(screen.getByRole("button", { name: "Select and move" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Eraser" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Delete region" })).toBeDisabled();
  });
});


import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  readWorkspaceFile: vi.fn(),
  saveWorkspaceFile: vi.fn(),
  listImageVersions: vi.fn(),
  fetchImageVersionDataUrl: vi.fn(),
}));

const pointer = vi.hoisted(() => ({ x: 0, y: 0 }));

vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  ...api,
}));

// Canvas does not run in happy-dom. The stage forwards pointer events and reports a pointer position, so a
// region can be drawn the way a user draws it.
vi.mock("react-konva", async () => {
  const React = await import("react");
  const passthrough = () => ({ children }: { children?: unknown }) =>
    React.createElement("div", null, children as never);
  return {
    Stage: React.forwardRef((props: {
      children?: unknown;
      onMouseDown?: () => void;
      onMouseMove?: () => void;
      onMouseUp?: () => void;
    }, ref: unknown) => {
      React.useImperativeHandle(ref as never, () => ({
        getRelativePointerPosition: () => ({ x: pointer.x, y: pointer.y }),
        getPointerPosition: () => ({ x: pointer.x, y: pointer.y }),
        getStage: () => null,
      }));
      return React.createElement("div", {
        "data-konva": "Stage",
        onMouseDown: props.onMouseDown,
        onMouseMove: props.onMouseMove,
        onMouseUp: props.onMouseUp,
      }, props.children as never);
    }),
    Layer: passthrough(),
    Image: passthrough(),
    Rect: passthrough(),
    Ellipse: passthrough(),
    Line: passthrough(),
    Circle: passthrough(),
    Text: passthrough(),
  };
});

import { ImageReviewPane, editRequestText } from "@/components/image/ImageReviewPane";
import { ApiError } from "@/lib/api";

const client = { requestMutation: vi.fn() } as never;
const VERSION = "a".repeat(32);

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
  api.saveWorkspaceFile.mockResolvedValue({ path: "x", version: "sha256:new", size: 1 });
  api.listImageVersions.mockResolvedValue([{
    id: VERSION,
    width: 400,
    height: 300,
    created_at: 1_700_000_000_000,
    report: [{ id: 1, status: "done", reason: "logo swapped" }],
  }]);
  api.fetchImageVersionDataUrl.mockResolvedValue("data:image/png;base64,BBBB");
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

async function stage(): Promise<HTMLElement> {
  let element: HTMLElement | null = null;
  await waitFor(() => {
    element = document.querySelector<HTMLElement>('[data-konva="Stage"]');
    expect(element).not.toBeNull();
  });
  return element as unknown as HTMLElement;
}

/** Draw a rectangle from one point to another, in stage pixels (the image is 560 × 420 at this size). */
async function drawRectangle(from: [number, number], to: [number, number]) {
  const element = await stage();
  pointer.x = from[0];
  pointer.y = from[1];
  fireEvent.mouseDown(element);
  pointer.x = to[0];
  pointer.y = to[1];
  fireEvent.mouseMove(element);
  fireEvent.mouseUp(element);
}

describe("versions and the report (IM-12, IM-13)", () => {
  it("lists the versions of the image and shows the report next to its region", async () => {
    renderPane();
    await drawRectangle([100, 50], [300, 200]);
    expect(await screen.findByRole("combobox", { name: "Version" })).toBeInTheDocument();

    fireEvent.change(screen.getByRole("combobox", { name: "Version" }), { target: { value: VERSION } });
    expect(await screen.findByText("Done")).toBeInTheDocument();
    expect(screen.getByText("logo swapped")).toBeInTheDocument();
    expect(api.listImageVersions).toHaveBeenCalledWith("t", "websocket:abc", "assets/banner.png");
  });

  it("compares the version with the original on a slider", async () => {
    renderPane();
    await screen.findByRole("combobox", { name: "Version" });
    fireEvent.change(screen.getByRole("combobox", { name: "Version" }), { target: { value: VERSION } });

    const compare = await screen.findByTestId("image-compare");
    expect(compare).toBeInTheDocument();
    expect(api.fetchImageVersionDataUrl).toHaveBeenCalledWith("t", "websocket:abc", VERSION);
    const slider = screen.getByRole("slider", { name: "Compare before and after" });
    fireEvent.change(slider, { target: { value: "30" } });
    expect(slider).toHaveValue("30");
  });
});

describe("resending only the regions not done (IM-14)", () => {
  it("keeps the done region's note, and asks the agent only about the others", async () => {
    const onSend = renderPane();
    await drawRectangle([100, 50], [300, 200]); // region 1
    await screen.findByRole("combobox", { name: "Version" });
    fireEvent.change(screen.getByRole("combobox", { name: "Version" }), { target: { value: VERSION } });
    await screen.findByText("logo swapped");
    fireEvent.click(screen.getByRole("button", { name: "Mark up" }));
    await drawRectangle([350, 60], [500, 160]); // region 2, added after the first round

    expect(screen.getByLabelText("Note for region 1")).toBeDisabled();
    expect(screen.getByLabelText("Note for region 2")).toBeEnabled();

    fireEvent.click(screen.getByRole("button", { name: "Resend the regions not done" }));
    await waitFor(() => expect(onSend).toHaveBeenCalledTimes(1));
    expect(onSend).toHaveBeenCalledWith(editRequestText("assets/banner.png", "assets/banner.annotations.json", [2]));
    expect(onSend.mock.calls[0][0]).toContain("Redo only regions 2");
  });

  it("does not offer a resend when every region is done", async () => {
    api.listImageVersions.mockResolvedValue([{
      id: VERSION, width: 400, height: 300, created_at: 1, report: [{ id: 1, status: "done", reason: "ok" }],
    }]);
    renderPane();
    await drawRectangle([100, 50], [300, 200]);
    await screen.findByRole("combobox", { name: "Version" });
    fireEvent.change(screen.getByRole("combobox", { name: "Version" }), { target: { value: VERSION } });

    expect(await screen.findByRole("button", { name: "Resend the regions not done" })).toBeDisabled();
  });
});

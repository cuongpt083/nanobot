import { afterEach, describe, expect, it, vi } from "vitest";

import { addRegion, emptyDoc } from "@/components/image/annotation-model";
import { annotatedPictureName, renderAnnotatedImage } from "@/components/image/annotated-image";

function stubCanvas(context: Record<string, unknown> | null) {
  const ctx = {
    drawImage: vi.fn(), save: vi.fn(), restore: vi.fn(), beginPath: vi.fn(), rect: vi.fn(),
    ellipse: vi.fn(), stroke: vi.fn(), fill: vi.fn(), moveTo: vi.fn(), lineTo: vi.fn(), arc: vi.fn(),
    fillText: vi.fn(), setLineDash: vi.fn(),
  };
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue((context ? ctx : null) as never);
  vi.spyOn(HTMLCanvasElement.prototype, "toDataURL").mockReturnValue("data:image/png;base64,DDDD");
  return ctx;
}

function image(width: number, height: number) {
  return { naturalWidth: width, naturalHeight: height } as HTMLImageElement;
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("renderAnnotatedImage", () => {
  it("draws the image at its own size, capped at the transport limit", () => {
    const ctx = stubCanvas({});
    renderAnnotatedImage(image(3200, 1600), emptyDoc());
    expect(ctx.drawImage).toHaveBeenCalledWith(expect.anything(), 0, 0, 1600, 800);
  });

  it("draws a small image at its own size", () => {
    const ctx = stubCanvas({});
    renderAnnotatedImage(image(300, 200), emptyDoc());
    expect(ctx.drawImage).toHaveBeenCalledWith(expect.anything(), 0, 0, 300, 200);
  });

  it("draws each region with its number, in the same place the pane shows it", () => {
    const ctx = stubCanvas({});
    const doc = addRegion(emptyDoc(), { shape: "rect", box: [0.1, 0.2, 0.5, 0.6] });
    renderAnnotatedImage(image(100, 100), doc);
    expect(ctx.rect).toHaveBeenCalledWith(10, 20, 40, 40);
    expect(ctx.fillText).toHaveBeenCalledWith("1", expect.any(Number), expect.any(Number));
  });

  it("returns null when there is no canvas to draw on", () => {
    stubCanvas(null);
    expect(renderAnnotatedImage(image(100, 100), emptyDoc())).toBeNull();
  });

  it("returns null for an image that has not loaded", () => {
    stubCanvas({});
    expect(renderAnnotatedImage(image(0, 0), emptyDoc())).toBeNull();
  });
});

describe("annotatedPictureName", () => {
  it("marks the picture as annotated and keeps the image's own name", () => {
    expect(annotatedPictureName("assets/banner.v3.png", "data:image/png;base64,AA")).toBe("banner.v3.annotated.png");
    expect(annotatedPictureName("photo.jpg", "data:image/jpeg;base64,AA")).toBe("photo.annotated.jpg");
  });
});

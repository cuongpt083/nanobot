import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mermaid = vi.hoisted(() => ({
  initialize: vi.fn(),
  render: vi.fn(),
  registerLayoutLoaders: vi.fn(),
}));
const panzoom = vi.hoisted(() => ({
  zoomIn: vi.fn(),
  zoomOut: vi.fn(),
  reset: vi.fn(),
  zoomWithWheel: vi.fn(),
  destroy: vi.fn(),
}));

vi.mock("mermaid", () => ({ default: mermaid }));
vi.mock("@mermaid-js/layout-elk", () => ({ default: [{ name: "elk", algorithm: "elk.layered" }] }));
vi.mock("@panzoom/panzoom", () => ({ default: vi.fn(() => panzoom) }));

import { MermaidPane } from "@/components/mermaid/MermaidPane";

// happy-dom's WheelEvent constructor drops ctrlKey; browsers keep it. Set it explicitly so the
// test exercises the component's branch rather than the test environment.
function wheel({ deltaY, ctrlKey }: { deltaY: number; ctrlKey: boolean }): WheelEvent {
  const event = new WheelEvent("wheel", { deltaY, bubbles: true, cancelable: true });
  Object.defineProperty(event, "ctrlKey", { value: ctrlKey });
  return event;
}

const SVG_A = '<svg id="a"><text>A</text></svg>';

beforeEach(() => {
  vi.clearAllMocks();
  // No observer: the pane treats the block as visible at once, so the tests do not depend on layout.
  vi.stubGlobal("IntersectionObserver", undefined);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("MermaidPane", () => {
  it("renders a finished block with the ELK layout and strict sanitization", async () => {
    mermaid.render.mockResolvedValue({ svg: SVG_A });
    render(<MermaidPane code={"graph TD\nA-->B"} />);

    await waitFor(() => expect(screen.getByRole("img", { name: "Diagram" }).innerHTML).toContain("<text>A</text>"));
    expect(mermaid.registerLayoutLoaders).toHaveBeenCalledTimes(1);
    expect(mermaid.initialize).toHaveBeenLastCalledWith(
      expect.objectContaining({ securityLevel: "strict", layout: "elk", theme: "default" }),
    );
    expect(mermaid.render).toHaveBeenCalledWith(expect.any(String), "graph TD\nA-->B");
  });

  it("does not render while the message is still streaming, then renders once it finishes", async () => {
    mermaid.render.mockResolvedValue({ svg: SVG_A });
    const { rerender } = render(<MermaidPane code={"graph TD\nA-->"} streaming />);

    await new Promise((resolve) => setTimeout(resolve, 300));
    expect(mermaid.render).not.toHaveBeenCalled();
    expect(screen.getByText(/graph TD/)).toBeInTheDocument(); // the raw source stands in

    rerender(<MermaidPane code={"graph TD\nA-->B"} streaming={false} />);
    await waitFor(() => expect(mermaid.render).toHaveBeenCalledTimes(1));
  });

  it("keeps the last good diagram and reports the line when a later edit is invalid", async () => {
    mermaid.render.mockResolvedValueOnce({ svg: SVG_A });
    const { rerender } = render(<MermaidPane code={"graph TD\nA-->B"} />);
    await waitFor(() => expect(screen.getByRole("img", { name: "Diagram" })).toBeInTheDocument());

    mermaid.render.mockRejectedValueOnce(new Error("Parse error on line 2:\n...A-->\nExpecting 'NODE' got 'EOF'"));
    rerender(<MermaidPane code={"graph TD\nA-->"} />);

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Syntax error on line 2");
    expect(alert).toHaveTextContent("Parse error on line 2");
    expect(screen.getByRole("img", { name: "Diagram" }).innerHTML).toContain("<text>A</text>");
  });

  it("zooms with Ctrl+wheel only, so a plain wheel still scrolls the page", async () => {
    mermaid.render.mockResolvedValue({ svg: SVG_A });
    render(<MermaidPane code={"graph TD\nA-->B"} />);
    const diagram = await screen.findByRole("img", { name: "Diagram" });
    const pane = screen.getByTestId("mermaid-pane");

    const plain = wheel({ deltaY: 40, ctrlKey: false });
    pane.dispatchEvent(plain);
    expect(panzoom.zoomWithWheel).not.toHaveBeenCalled();
    expect(plain.defaultPrevented).toBe(false);

    const ctrl = wheel({ deltaY: -40, ctrlKey: true });
    diagram.dispatchEvent(ctrl);
    expect(panzoom.zoomWithWheel).toHaveBeenCalledTimes(1);
    expect(ctrl.defaultPrevented).toBe(true);
  });

  it("wires the toolbar to the zoom controller and toggles full screen", async () => {
    mermaid.render.mockResolvedValue({ svg: SVG_A });
    render(<MermaidPane code={"graph TD\nA-->B"} />);
    await screen.findByRole("img", { name: "Diagram" });

    fireEvent.click(screen.getByRole("button", { name: "Zoom in" }));
    fireEvent.click(screen.getByRole("button", { name: "Zoom out" }));
    fireEvent.click(screen.getByRole("button", { name: "Fit" }));
    expect(panzoom.zoomIn).toHaveBeenCalledTimes(1);
    expect(panzoom.zoomOut).toHaveBeenCalledTimes(1);
    expect(panzoom.reset).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole("button", { name: "Full screen" }));
    expect(screen.getByRole("button", { name: "Exit full screen" })).toBeInTheDocument();
    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.getByRole("button", { name: "Full screen" })).toBeInTheDocument();
  });

  it("shows the source and no toolbar action that needs an SVG when the first render fails", async () => {
    mermaid.render.mockRejectedValue(new Error("Unknown diagram type"));
    render(<MermaidPane code={"not a diagram"} />);

    await screen.findByRole("alert");
    expect(screen.getByText("not a diagram")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Zoom in" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Download SVG" })).toBeDisabled();
  });
});

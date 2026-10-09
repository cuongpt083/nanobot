import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/components/mermaid/MermaidPane", () => ({
  MermaidPane: ({ code, streaming }: { code: string; streaming?: boolean }) => (
    <div data-testid="stub-mermaid" data-streaming={String(Boolean(streaming))}>{code}</div>
  ),
}));

import MarkdownTextRenderer from "@/components/MarkdownTextRenderer";

describe("MarkdownTextRenderer mermaid fences", () => {
  it("sends a mermaid fence to the diagram pane instead of the code block", async () => {
    render(<MarkdownTextRenderer>{"```mermaid\ngraph TD\nA-->B\n```"}</MarkdownTextRenderer>);

    const pane = await screen.findByTestId("stub-mermaid");
    expect(pane).toHaveTextContent("graph TD");
    expect(pane).toHaveTextContent("A-->B");
    expect(pane).toHaveAttribute("data-streaming", "false");
  });

  it("keeps other fenced languages on the ordinary code path", async () => {
    render(<MarkdownTextRenderer>{"```python\nprint('hi')\n```"}</MarkdownTextRenderer>);

    expect(await screen.findByText("print('hi')")).toBeInTheDocument();
    expect(screen.queryByTestId("stub-mermaid")).toBeNull();
  });
});

import { describe, expect, it } from "vitest";

import { mermaidInitOptions, summarizeError, syntaxErrorLine } from "@/components/mermaid/mermaid-config";

describe("mermaidInitOptions", () => {
  it("uses ELK layout and strict sanitization in both themes", () => {
    for (const dark of [false, true]) {
      const options = mermaidInitOptions(dark);
      expect(options).toMatchObject({ startOnLoad: false, securityLevel: "strict", layout: "elk" });
      expect(options.theme).toBe(dark ? "dark" : "default");
    }
  });

  it("keeps labels at their natural size for flowcharts and long sequence diagrams", () => {
    const options = mermaidInitOptions(false);
    expect(options.flowchart.useMaxWidth).toBe(false);
    expect(options.sequence).toEqual({ useMaxWidth: false, wrap: true, mirrorActors: false });
  });
});

describe("syntaxErrorLine", () => {
  it("reads the line number mermaid reports", () => {
    expect(syntaxErrorLine("Parse error on line 3:\n...")).toBe(3);
    expect(syntaxErrorLine("Lexical error on LINE 12")).toBe(12);
  });

  it("returns null when the error names no line", () => {
    expect(syntaxErrorLine("Unknown diagram type")).toBeNull();
  });
});

describe("summarizeError", () => {
  it("keeps the first meaningful line and trims mermaid's context dump", () => {
    expect(summarizeError("\n  Parse error on line 2:\n...A-->\nExpecting 'NODE'")).toBe("Parse error on line 2:");
  });

  it("falls back to a generic message and caps the length", () => {
    expect(summarizeError("   ")).toBe("Mermaid render failed");
    expect(summarizeError("x".repeat(500))).toHaveLength(300);
  });
});

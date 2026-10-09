/**
 * Pure helpers for the Mermaid pane: the initialize() options and error parsing.
 *
 * Kept free of DOM and of the mermaid import so the choices here can be unit-tested without
 * rendering a diagram. Layout is ELK by default; a diagram that declares its own `layout` in its
 * frontmatter keeps it, because mermaid reads the frontmatter after the global config.
 */

export interface MermaidInitOptions {
  startOnLoad: false;
  securityLevel: "strict";
  theme: "dark" | "default";
  layout: "elk";
  flowchart: { useMaxWidth: false };
  sequence: { useMaxWidth: false; wrap: true; mirrorActors: false };
}

export function mermaidInitOptions(dark: boolean): MermaidInitOptions {
  return {
    startOnLoad: false,
    // "strict" makes mermaid sanitize its own SVG output; the pane injects that SVG as HTML.
    securityLevel: "strict",
    theme: dark ? "dark" : "default",
    layout: "elk",
    // Labels must keep their size; scaling the whole diagram to the column width is what made
    // 15-participant sequence diagrams unreadable.
    flowchart: { useMaxWidth: false },
    sequence: { useMaxWidth: false, wrap: true, mirrorActors: false },
  };
}

/** The line number mermaid reports for a syntax error ("Parse error on line 3: ..."), if any. */
export function syntaxErrorLine(message: string): number | null {
  const match = /line\s+(\d+)/i.exec(message);
  return match ? Number(match[1]) : null;
}

/** The first meaningful line of an error, without mermaid's repeated context dumps. */
export function summarizeError(message: string): string {
  const first = message.split("\n").map((line) => line.trim()).find((line) => line.length > 0);
  return (first ?? "Mermaid render failed").slice(0, 300);
}

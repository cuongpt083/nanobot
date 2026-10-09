/**
 * Lazy loader for mermaid and its ELK layout. Nothing here is imported statically by the chat
 * bundle: the first diagram on screen pays the download, every other reply pays nothing.
 */

type MermaidModule = typeof import("mermaid");

let ready: Promise<MermaidModule["default"]> | null = null;

export function loadMermaid(): Promise<MermaidModule["default"]> {
  if (!ready) {
    ready = Promise.all([import("mermaid"), import("@mermaid-js/layout-elk")]).then(
      ([mermaidModule, elkModule]) => {
        const mermaid = mermaidModule.default;
        // ELK 0.2.x declares mermaid ^11 as its peer; the 1.x line needs mermaid 12.
        mermaid.registerLayoutLoaders(elkModule.default);
        return mermaid;
      },
    );
    // A failed download must not poison every later diagram in the session.
    ready.catch(() => {
      ready = null;
    });
  }
  return ready;
}

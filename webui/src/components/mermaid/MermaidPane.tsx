import { useCallback, useEffect, useId, useRef, useState, type MouseEvent } from "react";
import Panzoom, { type PanzoomObject } from "@panzoom/panzoom";
import { Copy, Download, Expand, Minimize, RotateCcw, ZoomIn, ZoomOut } from "lucide-react";
import { useTranslation } from "react-i18next";

import { useThemeValue } from "@/hooks/useTheme";
import { cn } from "@/lib/utils";

import { mermaidInitOptions, summarizeError, syntaxErrorLine } from "./mermaid-config";
import { loadMermaid } from "./mermaid-loader";

/** Wait this long after the last change before rendering, so typing or streaming does not thrash. */
const RENDER_DEBOUNCE_MS = 150;
const MIN_SCALE = 0.25;
const MAX_SCALE = 6;

interface MermaidPaneProps {
  code: string;
  /** The enclosing message is still streaming; the fence may be incomplete, so do not render yet. */
  streaming?: boolean;
}

/**
 * A Mermaid diagram inside a chat message: lazy render, Ctrl+wheel zoom, drag to pan, and a small toolbar.
 *
 * The SVG comes from mermaid with `securityLevel: "strict"`, which sanitizes it before it is
 * returned; it is injected as HTML only for that reason.
 */
export function MermaidPane({ code, streaming = false }: MermaidPaneProps) {
  const { t } = useTranslation();
  const dark = useThemeValue() === "dark";
  const id = useId().replace(/[^a-zA-Z0-9]/g, "");
  const hostRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLDivElement>(null);
  const panzoomRef = useRef<PanzoomObject | null>(null);
  const renderSeq = useRef(0);
  const [visible, setVisible] = useState(false);
  const [svg, setSvg] = useState("");
  const [error, setError] = useState<{ message: string; line: number | null } | null>(null);
  const [fullscreen, setFullscreen] = useState(false);
  const [copied, setCopied] = useState(false);

  // Do no layout work until the block is near the viewport; a long reply can hold many diagrams.
  useEffect(() => {
    const host = hostRef.current;
    if (!host || visible) return;
    if (typeof IntersectionObserver === "undefined") {
      setVisible(true);
      return;
    }
    const observer = new IntersectionObserver((entries) => {
      if (entries.some((entry) => entry.isIntersecting)) {
        setVisible(true);
        observer.disconnect();
      }
    }, { rootMargin: "200px" });
    observer.observe(host);
    return () => observer.disconnect();
  }, [visible]);

  // Render a finished block. While streaming the last good SVG stays on screen.
  useEffect(() => {
    if (streaming || !visible) return;
    const seq = ++renderSeq.current;
    const timer = window.setTimeout(async () => {
      try {
        const mermaid = await loadMermaid();
        mermaid.initialize(mermaidInitOptions(dark));
        const rendered = await mermaid.render(`mmd${id}${seq}`, code);
        if (seq !== renderSeq.current) return;
        setSvg(rendered.svg);
        setError(null);
      } catch (err) {
        if (seq !== renderSeq.current) return;
        const message = err instanceof Error ? err.message : String(err);
        // mermaid leaves its scratch element behind on failure; remove it so it does not pile up.
        document.getElementById(`dmmd${id}${seq}`)?.remove();
        setError({ message: summarizeError(message), line: syntaxErrorLine(message) });
      }
    }, RENDER_DEBOUNCE_MS);
    return () => window.clearTimeout(timer);
  }, [code, dark, id, streaming, visible]);

  // Pan and pinch only: the wheel is handled below, and only with Ctrl, so plain scrolling still
  // scrolls the chat.
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !svg) return;
    const instance = Panzoom(canvas, { minScale: MIN_SCALE, maxScale: MAX_SCALE, cursor: "grab" });
    panzoomRef.current = instance;
    return () => {
      instance.destroy();
      panzoomRef.current = null;
    };
  }, [svg]);

  // React's wheel listeners are passive, so preventDefault needs a native listener.
  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    const onWheel = (event: WheelEvent) => {
      if (!event.ctrlKey || !panzoomRef.current) return; // plain wheel: let the page scroll
      event.preventDefault();
      panzoomRef.current.zoomWithWheel(event);
    };
    host.addEventListener("wheel", onWheel, { passive: false });
    return () => host.removeEventListener("wheel", onWheel);
  }, []);

  useEffect(() => {
    if (!fullscreen) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setFullscreen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [fullscreen]);

  const zoomBy = useCallback((direction: "in" | "out") => {
    const instance = panzoomRef.current;
    if (!instance) return;
    if (direction === "in") instance.zoomIn();
    else instance.zoomOut();
  }, []);

  const fit = useCallback(() => panzoomRef.current?.reset(), []);

  const downloadSvg = useCallback(() => {
    if (!svg) return;
    saveBlob(new Blob([svg], { type: "image/svg+xml" }), "diagram.svg");
  }, [svg]);

  const downloadPng = useCallback(async () => {
    if (!svg) return;
    try {
      saveBlob(await svgToPng(svg), "diagram.png");
    } catch {
      // Some SVGs taint the canvas; the SVG download is always available as a fallback.
    }
  }, [svg]);

  const copySource = useCallback(async (event: MouseEvent) => {
    event.stopPropagation();
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      // Clipboard may be blocked by the webview; the source is still visible below.
    }
  }, [code]);

  const hasSvg = svg.length > 0;
  const toolbarButton = "inline-flex h-7 w-7 items-center justify-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground disabled:opacity-40";

  return (
    <div
      ref={hostRef}
      className={cn(
        "my-3 overflow-hidden rounded-md border border-border/60 bg-background",
        fullscreen && "fixed inset-4 z-50 my-0 flex flex-col shadow-xl",
      )}
      data-testid="mermaid-pane"
    >
      <div className="flex items-center justify-end gap-0.5 border-b border-border/50 px-1.5 py-1">
        <button type="button" className={toolbarButton} disabled={!hasSvg}
          aria-label={t("mermaid.zoomIn", { defaultValue: "Zoom in" })} onClick={() => zoomBy("in")}>
          <ZoomIn className="h-3.5 w-3.5" />
        </button>
        <button type="button" className={toolbarButton} disabled={!hasSvg}
          aria-label={t("mermaid.zoomOut", { defaultValue: "Zoom out" })} onClick={() => zoomBy("out")}>
          <ZoomOut className="h-3.5 w-3.5" />
        </button>
        <button type="button" className={toolbarButton} disabled={!hasSvg}
          aria-label={t("mermaid.fit", { defaultValue: "Fit" })} onClick={fit}>
          <RotateCcw className="h-3.5 w-3.5" />
        </button>
        <button type="button" className={toolbarButton} disabled={!hasSvg}
          aria-label={t("mermaid.downloadSvg", { defaultValue: "Download SVG" })} onClick={downloadSvg}>
          <Download className="h-3.5 w-3.5" />
        </button>
        <button type="button" className={toolbarButton} disabled={!hasSvg}
          aria-label={t("mermaid.downloadPng", { defaultValue: "Download PNG" })} onClick={() => void downloadPng()}>
          <span className="text-[10px] font-medium">PNG</span>
        </button>
        <button type="button" className={toolbarButton}
          aria-label={t("mermaid.copySource", { defaultValue: "Copy source" })} onClick={copySource}>
          {copied ? <span className="text-[10px]">✓</span> : <Copy className="h-3.5 w-3.5" />}
        </button>
        <button type="button" className={toolbarButton}
          aria-label={fullscreen
            ? t("mermaid.exitFullscreen", { defaultValue: "Exit full screen" })
            : t("mermaid.fullscreen", { defaultValue: "Full screen" })}
          onClick={() => setFullscreen((value) => !value)}>
          {fullscreen ? <Minimize className="h-3.5 w-3.5" /> : <Expand className="h-3.5 w-3.5" />}
        </button>
      </div>

      {error ? (
        <div role="alert" className="border-b border-red-500/25 bg-red-500/10 px-3 py-2 text-xs text-red-600 dark:text-red-300">
          {error.line !== null
            ? t("mermaid.syntaxErrorLine", { line: error.line, defaultValue: "Syntax error on line {{line}}" })
            : t("mermaid.renderError", { defaultValue: "Diagram could not be rendered" })}
          {": "}{error.message}
        </div>
      ) : null}

      {hasSvg ? (
        <div className={cn("overflow-hidden p-3", fullscreen && "flex-1")} onDoubleClick={fit}>
          <div
            ref={canvasRef}
            role="img"
            aria-label={t("mermaid.diagram", { defaultValue: "Diagram" })}
            className="inline-block cursor-grab active:cursor-grabbing"
            dangerouslySetInnerHTML={{ __html: svg }}
          />
        </div>
      ) : (
        // Nothing rendered yet (streaming, off-screen, or a failed first render): show the source.
        <pre className="m-0 overflow-x-auto p-3 text-xs text-muted-foreground">
          <code>{code}</code>
        </pre>
      )}

      {hasSvg && !fullscreen ? (
        <p className="m-0 px-3 pb-2 text-[11px] text-muted-foreground/70">
          {t("mermaid.zoomHint", { defaultValue: "Ctrl + scroll to zoom · drag to pan · double-click to fit" })}
        </p>
      ) : null}
    </div>
  );
}

function saveBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

async function svgToPng(svg: string): Promise<Blob> {
  const url = URL.createObjectURL(new Blob([svg], { type: "image/svg+xml" }));
  try {
    const image = new Image();
    await new Promise<void>((resolve, reject) => {
      image.onload = () => resolve();
      image.onerror = () => reject(new Error("svg image failed to load"));
      image.src = url;
    });
    const canvas = document.createElement("canvas");
    canvas.width = image.naturalWidth || 800;
    canvas.height = image.naturalHeight || 600;
    const context = canvas.getContext("2d");
    if (!context) throw new Error("no 2d context");
    context.fillStyle = "#ffffff";
    context.fillRect(0, 0, canvas.width, canvas.height);
    context.drawImage(image, 0, 0);
    return await new Promise<Blob>((resolve, reject) => {
      canvas.toBlob((blob) => (blob ? resolve(blob) : reject(new Error("png encode failed"))), "image/png");
    });
  } finally {
    URL.revokeObjectURL(url);
  }
}

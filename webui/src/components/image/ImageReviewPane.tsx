import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
import { Circle, Ellipse, Image as KonvaImage, Layer, Line, Rect, Stage, Text } from "react-konva";
import type Konva from "konva";
import { useTranslation } from "react-i18next";

import {
  BRUSH_RADIUS,
  MAX_BRUSH_POINTS,
  MAX_REGIONS,
  addRegion,
  boxFromCorners,
  canAddRegion,
  commit,
  createHistory,
  emptyDoc,
  redo,
  regionLabel,
  removeRegion,
  setCompositeToOriginal,
  setGlobalNote,
  setNote,
  toPayload,
  undo,
  type Pair,
  type Region,
  type RegionShape,
} from "@/components/image/annotation-model";
import { ApiError, isWorkspaceConflict, readWorkspaceFile, saveWorkspaceFile, type WebUIMutationTransport } from "@/lib/api";
import { cn } from "@/lib/utils";

export type ImageTool = "select" | "pan" | RegionShape;

const PALETTE = ["#e11d48", "#2563eb", "#16a34a", "#d97706", "#7c3aed", "#0891b2"];
const MIN_ZOOM = 0.5;
const MAX_ZOOM = 8;
const SHAPE_TOOLS: RegionShape[] = ["rect", "ellipse", "brush", "pin"];

/** Where the annotation file sits next to the image: ``banner.v3.png`` → ``banner.v3.annotations.json``. */
export function annotationPathFor(imagePath: string): string {
  return imagePath.replace(/\.[^./\\]+$/, "") + ".annotations.json";
}

/** The message that asks the agent to act on the annotation file. Instructions are in English. */
export function editRequestText(imagePath: string, annotationPath: string): string {
  return [
    `Edit the image ${imagePath} following the region annotations in ${annotationPath}.`,
    "Use the image-region-edit skill and report the result region by region.",
  ].join(" ");
}

interface ImageReviewPaneProps {
  sessionKey: string;
  token: string;
  client: WebUIMutationTransport;
  /** Workspace path of the image. */
  path: string;
  /** The image as a data URL. */
  src: string;
  /** Sends the request message to the chat. */
  onSend: (content: string) => void;
}

interface Draft {
  shape: RegionShape;
  start: Pair;
  current: Pair;
  points: Pair[];
}

function clamp01(value: number): number {
  return Math.min(1, Math.max(0, value));
}

export function ImageReviewPane({ sessionKey, token, client, path, src, onSend }: ImageReviewPaneProps) {
  const { t } = useTranslation();
  const [history, setHistory] = useState(() => createHistory(emptyDoc()));
  const doc = history.present;
  const [tool, setTool] = useState<ImageTool>("rect");
  const [selected, setSelected] = useState<number | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [drafts, setDrafts] = useState<Record<number, string>>({});
  const [globalDraft, setGlobalDraft] = useState<string | null>(null);
  const [image, setImage] = useState<HTMLImageElement | null>(null);
  const [imageFailed, setImageFailed] = useState(false);
  const [view, setView] = useState({ scale: 1, x: 0, y: 0 });
  const [size, setSize] = useState({ width: 640, height: 420 });
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const stageRef = useRef<Konva.Stage | null>(null);

  const apply = (next: (current: typeof doc) => typeof doc) => {
    setHistory((current) => commit(current, next(current.present)));
  };

  useEffect(() => {
    let cancelled = false;
    const loaded = new window.Image();
    loaded.onload = () => {
      if (!cancelled) setImage(loaded);
    };
    loaded.onerror = () => {
      if (!cancelled) setImageFailed(true);
    };
    loaded.src = src;
    return () => {
      cancelled = true;
    };
  }, [src]);

  useEffect(() => {
    const element = containerRef.current;
    if (!element) return;
    const observer = new ResizeObserver(() => {
      setSize({ width: Math.max(160, element.clientWidth), height: Math.max(160, element.clientHeight) });
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  const naturalWidth = image?.naturalWidth ?? 0;
  const naturalHeight = image?.naturalHeight ?? 0;
  const fit = naturalWidth && naturalHeight
    ? Math.min(size.width / naturalWidth, size.height / naturalHeight)
    : 1;
  const displayWidth = naturalWidth * fit;
  const displayHeight = naturalHeight * fit;
  const shorter = Math.min(displayWidth, displayHeight);

  const toFraction = (point: { x: number; y: number }): Pair => [
    clamp01(point.x / displayWidth),
    clamp01(point.y / displayHeight),
  ];

  const pointer = (): Pair | null => {
    const stage = stageRef.current;
    const position = stage?.getRelativePointerPosition();
    return position ? toFraction(position) : null;
  };

  const onPointerDown = () => {
    if (!image || tool === "select" || tool === "pan") {
      if (tool === "select") setSelected(null);
      return;
    }
    const start = pointer();
    if (!start) return;
    if (tool === "pin") {
      if (!canAddRegion(doc)) {
        setError(t("image.review.limit", { defaultValue: "This image has the maximum number of regions." }));
        return;
      }
      apply((current) => addRegion(current, { shape: "pin", point: start }));
      return;
    }
    setDraft({ shape: tool, start, current: start, points: [start] });
  };

  const onPointerMove = () => {
    if (!draft) return;
    const at = pointer();
    if (!at) return;
    if (draft.shape === "brush") {
      if (draft.points.length >= MAX_BRUSH_POINTS) return;
      setDraft({ ...draft, current: at, points: [...draft.points, at] });
    } else {
      setDraft({ ...draft, current: at });
    }
  };

  const onPointerUp = () => {
    if (!draft) return;
    const finished = draft;
    setDraft(null);
    if (finished.shape === "brush") {
      if (finished.points.length < 1) return;
      apply((current) => addRegion(current, { shape: "brush", points: finished.points, radius: BRUSH_RADIUS }));
      return;
    }
    const box = boxFromCorners(finished.start, finished.current);
    if (!box) return;
    if (!canAddRegion(doc)) {
      setError(t("image.review.limit", { defaultValue: "This image has the maximum number of regions." }));
      return;
    }
    apply((current) => addRegion(current, { shape: finished.shape, box }));
  };

  const onWheel = (event: Konva.KonvaEventObject<WheelEvent>) => {
    event.evt.preventDefault();
    const stage = stageRef.current;
    const pos = stage?.getPointerPosition();
    if (!stage || !pos) return;
    const factor = event.evt.deltaY < 0 ? 1.1 : 1 / 1.1;
    setView((current) => {
      const scale = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, current.scale * factor));
      const ratio = scale / current.scale;
      return {
        scale,
        x: pos.x - (pos.x - current.x) * ratio,
        y: pos.y - (pos.y - current.y) * ratio,
      };
    });
  };

  const readRegion = (region: Region) => {
    if (region.shape === "pin" && region.point) {
      return { x: region.point[0] * displayWidth, y: region.point[1] * displayHeight };
    }
    return null;
  };

  const keyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const mod = event.ctrlKey || event.metaKey;
    if (!mod) return;
    const key = event.key.toLowerCase();
    if (key === "z" && !event.shiftKey) {
      event.preventDefault();
      setHistory((current) => undo(current));
    } else if (key === "y" || (key === "z" && event.shiftKey)) {
      event.preventDefault();
      setHistory((current) => redo(current));
    }
  };

  const noteValue = (region: Region) => drafts[region.id] ?? region.note;

  const commitNote = (id: number) => {
    const text = drafts[id];
    if (text === undefined) return;
    setDrafts((current) => {
      const next = { ...current };
      delete next[id];
      return next;
    });
    apply((current) => setNote(current, id, text));
  };

  const canSend = !sending && (doc.regions.length > 0 || doc.globalNote.trim().length > 0);

  const send = async () => {
    if (!canSend) return;
    setSending(true);
    setError(null);
    const annotationPath = annotationPathFor(path);
    try {
      let baseVersion: string | null = null;
      try {
        baseVersion = (await readWorkspaceFile(token, sessionKey, annotationPath)).version;
      } catch (reason) {
        if (!(reason instanceof ApiError && reason.status === 404)) throw reason;
      }
      await saveWorkspaceFile(client, sessionKey, {
        path: annotationPath,
        content: JSON.stringify(toPayload(doc, path, null), null, 2),
        baseVersion,
      });
      onSend(editRequestText(path, annotationPath));
    } catch (reason) {
      setError(isWorkspaceConflict(reason)
        ? t("image.review.conflict", { defaultValue: "The annotation file changed on disk. Reload the image and try again." })
        : t("image.review.sendFailed", { defaultValue: "The edit request could not be saved." }));
    } finally {
      setSending(false);
    }
  };

  const tools = useMemo(() => [
    { id: "select" as const, label: t("image.review.tool.select", { defaultValue: "Select" }) },
    { id: "pan" as const, label: t("image.review.tool.pan", { defaultValue: "Pan" }) },
    ...SHAPE_TOOLS.map((shape) => ({
      id: shape,
      label: t(`image.review.tool.${shape}`, {
        defaultValue: { rect: "Rectangle", ellipse: "Ellipse", brush: "Brush", pin: "Pin" }[shape],
      }),
    })),
  ], [t]);

  if (imageFailed) {
    return (
      <div role="alert" className="p-4 text-sm text-red-600 dark:text-red-300">
        {t("image.review.loadFailed", { defaultValue: "The image could not be loaded." })}
      </div>
    );
  }

  const colorOf = (id: number) => PALETTE[(id - 1) % PALETTE.length];

  return (
    <div className="flex h-full min-h-0 flex-col" data-testid="image-review-pane" tabIndex={-1} onKeyDown={keyDown}>
      <div role="toolbar" aria-label={t("image.review.toolbar", { defaultValue: "Image tools" })}
        className="flex flex-wrap items-center gap-1 border-b border-border/50 px-2 py-1 text-xs">
        {tools.map((item) => (
          <button key={item.id} type="button" aria-pressed={tool === item.id}
            onClick={() => setTool(item.id)}
            className={cn("rounded px-2 py-1", tool === item.id ? "bg-muted font-medium" : "text-muted-foreground")}>
            {item.label}
          </button>
        ))}
        <span className="mx-1 h-4 w-px bg-border/70" aria-hidden />
        <button type="button" aria-label={t("image.review.undo", { defaultValue: "Undo" })}
          disabled={history.past.length === 0} onClick={() => setHistory((current) => undo(current))}
          className="rounded px-2 py-1 disabled:opacity-40">↶</button>
        <button type="button" aria-label={t("image.review.redo", { defaultValue: "Redo" })}
          disabled={history.future.length === 0} onClick={() => setHistory((current) => redo(current))}
          className="rounded px-2 py-1 disabled:opacity-40">↷</button>
        <button type="button" onClick={() => setView({ scale: 1, x: 0, y: 0 })}
          className="rounded px-2 py-1 text-muted-foreground">
          {t("image.review.fit", { defaultValue: "Fit" })}
        </button>
        <label className="ml-auto flex items-center gap-1 text-muted-foreground">
          <input type="checkbox" checked={doc.compositeToOriginal}
            onChange={(event) => apply((current) => setCompositeToOriginal(current, event.target.checked))} />
          {t("image.review.onlyInside", { defaultValue: "Change only inside the marked areas" })}
        </label>
      </div>

      <div className="flex min-h-0 flex-1 flex-col lg:flex-row">
        <div ref={containerRef} className="relative min-h-[240px] min-w-0 flex-1 bg-muted/30">
          {image ? (
            <Stage
              ref={stageRef}
              width={size.width}
              height={size.height}
              scaleX={view.scale}
              scaleY={view.scale}
              x={view.x}
              y={view.y}
              draggable={tool === "pan"}
              onWheel={onWheel}
              onDragEnd={(event) => setView((current) => ({ ...current, x: event.target.x(), y: event.target.y() }))}
              onMouseDown={onPointerDown}
              onTouchStart={onPointerDown}
              onMouseMove={onPointerMove}
              onTouchMove={onPointerMove}
              onMouseUp={onPointerUp}
              onTouchEnd={onPointerUp}
            >
              <Layer>
                <KonvaImage image={image} width={displayWidth} height={displayHeight} />
                {doc.regions.map((region) => {
                  const color = colorOf(region.id);
                  const isSelected = selected === region.id;
                  const onSelect = () => setSelected(region.id);
                  if (region.shape === "rect" && region.box) {
                    const [x0, y0, x1, y1] = region.box;
                    return (
                      <Rect key={region.id} x={x0 * displayWidth} y={y0 * displayHeight}
                        width={(x1 - x0) * displayWidth} height={(y1 - y0) * displayHeight}
                        stroke={color} strokeWidth={(isSelected ? 3 : 2) / view.scale} fill={`${color}22`} onClick={onSelect} onTap={onSelect} />
                    );
                  }
                  if (region.shape === "ellipse" && region.box) {
                    const [x0, y0, x1, y1] = region.box;
                    return (
                      <Ellipse key={region.id}
                        x={((x0 + x1) / 2) * displayWidth} y={((y0 + y1) / 2) * displayHeight}
                        radiusX={((x1 - x0) * displayWidth) / 2} radiusY={((y1 - y0) * displayHeight) / 2}
                        stroke={color} strokeWidth={(isSelected ? 3 : 2) / view.scale} fill={`${color}22`} onClick={onSelect} onTap={onSelect} />
                    );
                  }
                  if (region.shape === "brush" && region.points) {
                    return (
                      <Line key={region.id}
                        points={region.points.flatMap(([x, y]) => [x * displayWidth, y * displayHeight])}
                        stroke={color} opacity={0.4}
                        strokeWidth={2 * (region.radius ?? BRUSH_RADIUS) * shorter}
                        lineCap="round" lineJoin="round" onClick={onSelect} onTap={onSelect} />
                    );
                  }
                  const at = readRegion(region);
                  return at ? (
                    <Circle key={region.id} x={at.x} y={at.y} radius={8 / view.scale}
                      fill={color} stroke="#ffffff" strokeWidth={2 / view.scale} onClick={onSelect} onTap={onSelect} />
                  ) : null;
                })}
                {doc.regions.map((region) => {
                  const anchor = region.shape === "pin" && region.point
                    ? [region.point[0] * displayWidth, region.point[1] * displayHeight]
                    : region.box
                      ? [region.box[0] * displayWidth, region.box[1] * displayHeight]
                      : region.points?.[0]
                        ? [region.points[0][0] * displayWidth, region.points[0][1] * displayHeight]
                        : null;
                  if (!anchor) return null;
                  return (
                    <Text key={`label-${region.id}`} x={anchor[0] + 4 / view.scale} y={anchor[1] + 4 / view.scale}
                      text={String(region.id)} fontSize={14 / view.scale} fontStyle="bold" fill={colorOf(region.id)} listening={false} />
                  );
                })}
                {draft && draft.shape === "rect" ? (
                  <Rect x={Math.min(draft.start[0], draft.current[0]) * displayWidth}
                    y={Math.min(draft.start[1], draft.current[1]) * displayHeight}
                    width={Math.abs(draft.current[0] - draft.start[0]) * displayWidth}
                    height={Math.abs(draft.current[1] - draft.start[1]) * displayHeight}
                    stroke="#111827" dash={[6 / view.scale, 4 / view.scale]} strokeWidth={1.5 / view.scale} listening={false} />
                ) : null}
                {draft && draft.shape === "ellipse" ? (
                  <Ellipse x={((draft.start[0] + draft.current[0]) / 2) * displayWidth}
                    y={((draft.start[1] + draft.current[1]) / 2) * displayHeight}
                    radiusX={(Math.abs(draft.current[0] - draft.start[0]) * displayWidth) / 2}
                    radiusY={(Math.abs(draft.current[1] - draft.start[1]) * displayHeight) / 2}
                    stroke="#111827" dash={[6 / view.scale, 4 / view.scale]} strokeWidth={1.5 / view.scale} listening={false} />
                ) : null}
                {draft && draft.shape === "brush" ? (
                  <Line points={draft.points.flatMap(([x, y]) => [x * displayWidth, y * displayHeight])}
                    stroke="#111827" opacity={0.3} strokeWidth={2 * BRUSH_RADIUS * shorter}
                    lineCap="round" lineJoin="round" listening={false} />
                ) : null}
              </Layer>
            </Stage>
          ) : (
            <p role="status" className="p-4 text-sm text-muted-foreground">
              {t("image.review.loading", { defaultValue: "Loading image..." })}
            </p>
          )}
        </div>

        <aside className="flex min-h-0 w-full flex-col gap-2 overflow-auto border-t border-border/50 p-3 lg:w-72 lg:border-l lg:border-t-0">
          <label className="flex flex-col gap-1 text-xs text-muted-foreground">
            {t("image.review.globalNote", { defaultValue: "Note for the whole image" })}
            <textarea className="min-h-[52px] rounded border border-border/60 bg-background p-2 text-sm text-foreground"
              value={globalDraft ?? doc.globalNote}
              onChange={(event) => setGlobalDraft(event.target.value)}
              onBlur={() => {
                if (globalDraft === null) return;
                const text = globalDraft;
                setGlobalDraft(null);
                apply((current) => setGlobalNote(current, text));
              }} />
          </label>

          {doc.regions.length === 0 ? (
            <p className="text-xs text-muted-foreground">
              {t("image.review.empty", { defaultValue: "Draw a rectangle, ellipse, brush stroke or pin on the image. Each gets a note." })}
            </p>
          ) : null}
          {doc.regions.map((region) => (
            <div key={region.id} className={cn("rounded border p-2 text-xs", selected === region.id ? "border-foreground/60" : "border-border/60")}
              onClick={() => setSelected(region.id)}>
              <div className="mb-1 flex items-center justify-between">
                <span className="font-medium" style={{ color: colorOf(region.id) }}>{regionLabel(region)}</span>
                <button type="button" className="text-muted-foreground underline"
                  onClick={() => apply((current) => removeRegion(current, region.id))}>
                  {t("image.review.remove", { defaultValue: "Remove" })}
                </button>
              </div>
              <textarea aria-label={t("image.review.noteFor", { defaultValue: "Note for region {{id}}", id: region.id })}
                className="min-h-[44px] w-full rounded border border-border/60 bg-background p-1.5 text-sm text-foreground"
                value={noteValue(region)}
                onChange={(event) => setDrafts((current) => ({ ...current, [region.id]: event.target.value }))}
                onBlur={() => commitNote(region.id)} />
            </div>
          ))}

          <p className="text-[11px] text-muted-foreground">
            {t("image.review.count", { defaultValue: "{{count}} of {{max}} regions", count: doc.regions.length, max: MAX_REGIONS })}
          </p>
          {error ? <p role="alert" className="text-xs text-red-600 dark:text-red-300">{error}</p> : null}
          <button type="button" disabled={!canSend} onClick={() => void send()}
            className="mt-auto rounded bg-foreground px-3 py-2 text-sm text-background disabled:opacity-50">
            {sending
              ? t("image.review.sending", { defaultValue: "Sending..." })
              : t("image.review.send", { defaultValue: "Send edits" })}
          </button>
        </aside>
      </div>
    </div>
  );
}

export default ImageReviewPane;

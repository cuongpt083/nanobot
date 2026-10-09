import { useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
import { Circle, Ellipse, Image as KonvaImage, Layer, Line, Rect, Stage, Text } from "react-konva";
import type Konva from "konva";
import { useTranslation } from "react-i18next";

import {
  BRUSH_SIZES,
  ERASER_COLOR,
  MAX_BRUSH_POINTS,
  MAX_REGIONS,
  addRegion,
  boxCorners,
  boxFromCorners,
  canAddRegion,
  commit,
  createHistory,
  emptyDoc,
  moveRegion,
  redo,
  regionLabel,
  removeRegion,
  resizeBox,
  setCompositeToOriginal,
  setGlobalNote,
  setNote,
  toPayload,
  undo,
  type BrushSize,
  type Corner,
  type Pair,
  regionColor,
  type Region,
  type RegionShape,
} from "@/components/image/annotation-model";
import { annotatedPictureName, renderAnnotatedImage } from "@/components/image/annotated-image";
import { loadVersionTree, type VersionRow } from "@/components/image/image-version-tree";
import type { SendAttachment } from "@/hooks/useNanobotStream";
import {
  ApiError,
  fetchImageVersionDataUrl,
  isWorkspaceConflict,
  listImageVersions,
  readWorkspaceFile,
  saveImageVersionToWorkspace,
  saveWorkspaceFile,
  type ImageVersionSummary,
  type WebUIMutationTransport,
} from "@/lib/api";
import { cn } from "@/lib/utils";

/** ``eraser`` is a brush stroke that removes from the marked area (IM-04). */
export type ImageTool = "select" | "pan" | RegionShape | "eraser";

const MIN_ZOOM = 0.5;
const MAX_ZOOM = 8;
const SHAPE_TOOLS: ImageTool[] = ["rect", "ellipse", "brush", "eraser", "pin"];
const TOOL_LABELS: Record<ImageTool, string> = {
  select: "Select and move",
  pan: "Pan",
  rect: "Rectangle",
  ellipse: "Ellipse",
  brush: "Brush",
  eraser: "Eraser",
  pin: "Pin",
};

const VERSION_FILE = /\.v\d+\.(png|jpe?g|webp)$/i;

/**
 * Where the annotation file sits next to the image. A saved version keeps ``<stem>.vN.annotations.json`` for the
 * request that made it, so an edit of that version is written to ``<stem>.vN.edit.annotations.json``.
 */
export function annotationPathFor(imagePath: string): string {
  const stem = imagePath.replace(/\.[^./\\]+$/, "");
  return VERSION_FILE.test(imagePath) ? `${stem}.edit.annotations.json` : `${stem}.annotations.json`;
}

/** The message that asks the agent to act on the annotation file. Instructions are in English. */
export function editRequestText(
  imagePath: string,
  annotationPath: string,
  redo?: number[],
  withPicture = false,
): string {
  const parts = [
    `Edit the image ${imagePath} following the region annotations in ${annotationPath}.`,
    "Use the image-region-edit skill and report the result region by region.",
  ];
  if (withPicture) {
    parts.push("The attached picture shows the marked regions with their numbers.");
  }
  if (redo && redo.length > 0) {
    parts.push(`Redo only regions ${redo.join(", ")}; keep the other regions as they are.`);
  }
  return parts.join(" ");
}

const STATUS_LABEL = { done: "Done", not_done: "Not done", partial: "Partly done" } as const;
const STATUS_STYLE = {
  done: "bg-emerald-500/15 text-emerald-700 dark:text-emerald-200",
  not_done: "bg-red-500/15 text-red-700 dark:text-red-200",
  partial: "bg-amber-500/15 text-amber-700 dark:text-amber-200",
} as const;

interface ImageReviewPaneProps {
  sessionKey: string;
  token: string;
  client: WebUIMutationTransport;
  /** Workspace path of the image. */
  path: string;
  /** The image as a data URL. */
  src: string;
  /** Sends the request message to the chat, with the marked picture attached when it could be drawn. */
  onSend: (content: string, attachments: SendAttachment[]) => void;
  /** Opens another image of the same family (a version in the tree) in the preview. */
  onOpenImage?: (path: string) => void;
}

interface Draft {
  shape: RegionShape;
  erase: boolean;
  radius: number;
  start: Pair;
  current: Pair;
  points: Pair[];
}

function clamp01(value: number): number {
  return Math.min(1, Math.max(0, value));
}

export function ImageReviewPane({ sessionKey, token, client, path, src, onSend, onOpenImage }: ImageReviewPaneProps) {
  const { t } = useTranslation();
  const [history, setHistory] = useState(() => createHistory(emptyDoc()));
  const doc = history.present;
  const [tool, setTool] = useState<ImageTool>("rect");
  const [brushSize, setBrushSize] = useState<BrushSize>("M");
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
  const [versions, setVersions] = useState<ImageVersionSummary[]>([]);
  const [activeVersionId, setActiveVersionId] = useState<string | null>(null);
  const [versionSrc, setVersionSrc] = useState<string | null>(null);
  const [comparePosition, setComparePosition] = useState(50);
  const [tree, setTree] = useState<VersionRow[]>([]);
  const [savedAs, setSavedAs] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  // Choosing a version shows the comparison; the user can go back to marking up without losing the version,
  // so the report and the resend still apply while regions are added or changed.
  const [showCompare, setShowCompare] = useState(true);
  const containerRef = useRef<HTMLDivElement>(null);
  const stageRef = useRef<Konva.Stage | null>(null);
  const activeVersion = versions.find((version) => version.id === activeVersionId) ?? null;

  const saveVersion = async () => {
    if (!activeVersion || saving) return;
    setSaving(true);
    setError(null);
    try {
      const saved = await saveImageVersionToWorkspace(client, sessionKey, activeVersion.id);
      setSavedAs(saved.path);
      await refreshTree();
    } catch {
      setError(t("image.review.saveFailed", { defaultValue: "The version could not be saved to the workspace." }));
    } finally {
      setSaving(false);
    }
  };
  const comparing = activeVersion !== null && versionSrc !== null && showCompare;

  // Versions the agent made from this image (IM-12). A list failure leaves the editor working without them.
  const refreshVersions = useCallback(async () => {
    try {
      setVersions(await listImageVersions(token, sessionKey, path));
    } catch {
      // The version list is a convenience.
    }
  }, [path, sessionKey, token]);

  useEffect(() => {
    void refreshVersions();
  }, [refreshVersions]);

  // The family of this image in its folder: the original and the saved versions (IM-15).
  const refreshTree = useCallback(async () => {
    setTree(await loadVersionTree(token, sessionKey, path));
  }, [path, sessionKey, token]);

  useEffect(() => {
    void refreshTree();
  }, [refreshTree]);

  useEffect(() => {
    if (!activeVersionId) {
      setVersionSrc(null);
      return;
    }
    let cancelled = false;
    fetchImageVersionDataUrl(token, sessionKey, activeVersionId)
      .then((url) => {
        if (!cancelled) setVersionSrc(url);
      })
      .catch(() => {
        if (!cancelled) setVersionSrc(null);
      });
    return () => {
      cancelled = true;
    };
  }, [activeVersionId, sessionKey, token]);

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
  const brushRadius = BRUSH_SIZES[brushSize];
  const editing = tool === "select";

  const toFraction = (point: { x: number; y: number }): Pair => [
    clamp01(point.x / displayWidth),
    clamp01(point.y / displayHeight),
  ];

  const pointer = (): Pair | null => {
    const position = stageRef.current?.getRelativePointerPosition();
    return position ? toFraction(position) : null;
  };

  const limitReached = () => {
    setError(t("image.review.limit", { defaultValue: "This image has the maximum number of regions." }));
  };

  const onStageDown = (event: Konva.KonvaEventObject<MouseEvent | TouchEvent>) => {
    if (!image) return;
    if (editing) {
      // Clicking empty image clears the selection; clicking a region is handled by the region itself.
      if (event.target === event.target.getStage()) setSelected(null);
      return;
    }
    if (tool === "pan") return;
    const start = pointer();
    if (!start) return;
    if (tool === "pin") {
      if (!canAddRegion(doc)) return limitReached();
      apply((current) => addRegion(current, { shape: "pin", point: start }));
      return;
    }
    const isBrush = tool === "brush" || tool === "eraser";
    setDraft({
      shape: isBrush ? "brush" : (tool as RegionShape),
      erase: tool === "eraser",
      radius: brushRadius,
      start,
      current: start,
      points: [start],
    });
  };

  const onStageMove = () => {
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

  const onStageUp = () => {
    if (!draft) return;
    const finished = draft;
    setDraft(null);
    if (finished.shape === "brush") {
      if (!canAddRegion(doc)) return limitReached();
      apply((current) => addRegion(current, {
        shape: "brush",
        points: finished.points,
        radius: finished.radius,
        ...(finished.erase ? { erase: true } : {}),
      }));
      return;
    }
    const box = boxFromCorners(finished.start, finished.current);
    if (!box) return;
    if (!canAddRegion(doc)) return limitReached();
    apply((current) => addRegion(current, { shape: finished.shape, box }));
  };

  const onWheel = (event: Konva.KonvaEventObject<WheelEvent>) => {
    event.evt.preventDefault();
    const pos = stageRef.current?.getPointerPosition();
    if (!pos) return;
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

  const removeSelected = () => {
    if (selected === null || lockedIds.has(selected)) return;
    apply((current) => removeRegion(current, selected));
    setSelected(null);
  };

  const keyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const target = event.target as HTMLElement;
    if (target.tagName === "TEXTAREA" || target.tagName === "INPUT") return;
    if ((event.key === "Delete" || event.key === "Backspace") && selected !== null) {
      event.preventDefault();
      removeSelected();
      return;
    }
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

  // IM-14: once a version has a report, its done regions keep their notes; only the rest is asked again.
  const reportById = new Map((activeVersion?.report ?? []).map((entry) => [entry.id, entry] as const));
  const resendMode = activeVersion !== null && reportById.size > 0;
  const lockedIds = new Set(resendMode
    ? [...reportById.values()].filter((entry) => entry.status === "done").map((entry) => entry.id)
    : []);
  const redoIds = resendMode ? doc.regions.map((region) => region.id).filter((id) => !lockedIds.has(id)) : [];
  const canSend = !sending && (resendMode
    ? redoIds.length > 0
    : doc.regions.length > 0 || doc.globalNote.trim().length > 0);

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
      const picture = image ? renderAnnotatedImage(image, doc) : null;
      const attachments: SendAttachment[] = picture
        ? [{
          media: { data_url: picture, name: annotatedPictureName(path, picture) },
          preview: { kind: "image", url: picture, name: annotatedPictureName(path, picture) },
        }]
        : [];
      onSend(
        editRequestText(path, annotationPath, resendMode ? redoIds : undefined, attachments.length > 0),
        attachments,
      );
      void refreshVersions();
    } catch (reason) {
      setError(isWorkspaceConflict(reason)
        ? t("image.review.conflict", { defaultValue: "The annotation file changed on disk. Reload the image and try again." })
        : t("image.review.sendFailed", { defaultValue: "The edit request could not be saved." }));
    } finally {
      setSending(false);
    }
  };

  const tools = useMemo(() => [
    { id: "select" as const, label: t("image.review.tool.select", { defaultValue: TOOL_LABELS.select }) },
    { id: "pan" as const, label: t("image.review.tool.pan", { defaultValue: TOOL_LABELS.pan }) },
    ...SHAPE_TOOLS.map((id) => ({
      id,
      label: t(`image.review.tool.${id}`, { defaultValue: TOOL_LABELS[id] }),
    })),
  ], [t]);

  if (imageFailed) {
    return (
      <div role="alert" className="p-4 text-sm text-red-600 dark:text-red-300">
        {t("image.review.loadFailed", { defaultValue: "The image could not be loaded." })}
      </div>
    );
  }

  const colorOf = regionColor;
  const zoom = view.scale;
  const dash = [6 / zoom, 4 / zoom];

  /** A drag of a region's node, expressed in fractions; the node goes back to where the document puts it. */
  const dragOffset = (node: Konva.Node, base: Pair) => {
    const dx = (node.x() - base[0]) / displayWidth;
    const dy = (node.y() - base[1]) / displayHeight;
    node.position({ x: base[0], y: base[1] });
    return [dx, dy] as Pair;
  };

  const renderShape = (region: Region) => {
    const color = colorOf(region);
    const isSelected = selected === region.id;
    const onSelect = () => setSelected(region.id);
    const draggable = editing && !lockedIds.has(region.id);
    const common = {
      onClick: onSelect,
      onTap: onSelect,
    };
    if ((region.shape === "rect" || region.shape === "ellipse") && region.box) {
      const [x0, y0, x1, y1] = region.box;
      const strokeWidth = (isSelected ? 3 : 2) / zoom;
      if (region.shape === "rect") {
        const base: Pair = [x0 * displayWidth, y0 * displayHeight];
        return (
          <Rect key={region.id} x={base[0]} y={base[1]}
            width={(x1 - x0) * displayWidth} height={(y1 - y0) * displayHeight}
            stroke={color} strokeWidth={strokeWidth} fill={`${color}22`} dash={region.erase ? dash : undefined}
            draggable={draggable}
            onDragEnd={(event) => {
              const [dx, dy] = dragOffset(event.target, base);
              apply((current) => moveRegion(current, region.id, dx, dy));
            }}
            {...common} />
        );
      }
      const center: Pair = [((x0 + x1) / 2) * displayWidth, ((y0 + y1) / 2) * displayHeight];
      return (
        <Ellipse key={region.id} x={center[0]} y={center[1]}
          radiusX={((x1 - x0) * displayWidth) / 2} radiusY={((y1 - y0) * displayHeight) / 2}
          stroke={color} strokeWidth={strokeWidth} fill={`${color}22`} dash={region.erase ? dash : undefined}
          draggable={draggable}
          onDragEnd={(event) => {
            const [dx, dy] = dragOffset(event.target, center);
            apply((current) => moveRegion(current, region.id, dx, dy));
          }}
          {...common} />
      );
    }
    if (region.shape === "brush" && region.points) {
      return (
        <Line key={region.id}
          points={region.points.flatMap(([x, y]) => [x * displayWidth, y * displayHeight])}
          stroke={color} opacity={region.erase ? 0.6 : 0.4} dash={region.erase ? dash : undefined}
          strokeWidth={2 * (region.radius ?? BRUSH_SIZES.M) * shorter}
          lineCap="round" lineJoin="round" draggable={draggable}
          onDragEnd={(event) => {
            const [dx, dy] = dragOffset(event.target, [0, 0]);
            apply((current) => moveRegion(current, region.id, dx, dy));
          }}
          {...common} />
      );
    }
    if (region.shape === "pin" && region.point) {
      const base: Pair = [region.point[0] * displayWidth, region.point[1] * displayHeight];
      return (
        <Circle key={region.id} x={base[0]} y={base[1]} radius={8 / zoom}
          fill={color} stroke="#ffffff" strokeWidth={2 / zoom} draggable={draggable}
          onDragEnd={(event) => {
            const [dx, dy] = dragOffset(event.target, base);
            apply((current) => moveRegion(current, region.id, dx, dy));
          }}
          {...common} />
      );
    }
    return null;
  };

  /** Corner handles for the selected rectangle or ellipse: drag one to resize, the opposite corner stays. */
  const renderHandles = (region: Region) => {
    if (!editing || lockedIds.has(region.id) || selected !== region.id || !region.box
      || region.shape === "brush" || region.shape === "pin") {
      return null;
    }
    const corners = boxCorners(region.box);
    return corners.map((corner, index) => {
      const at: Pair = [corner[0] * displayWidth, corner[1] * displayHeight];
      return (
        <Circle key={`handle-${region.id}-${index}`} x={at[0]} y={at[1]} radius={5 / zoom}
          fill="#ffffff" stroke="#111827" strokeWidth={1.5 / zoom} draggable
          onDragEnd={(event) => {
            const to = dragOffset(event.target, at);
            const fraction: Pair = [corner[0] + to[0], corner[1] + to[1]];
            apply((current) => resizeBox(current, region.id, index as Corner, fraction));
          }} />
      );
    });
  };

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
        {tool === "brush" || tool === "eraser" ? (
          <span role="group" aria-label={t("image.review.brushSize", { defaultValue: "Brush size" })} className="flex items-center gap-0.5">
            {(Object.keys(BRUSH_SIZES) as BrushSize[]).map((size) => (
              <button key={size} type="button" aria-pressed={brushSize === size} onClick={() => setBrushSize(size)}
                className={cn("h-6 w-6 rounded-full text-[11px]", brushSize === size ? "bg-muted font-medium" : "text-muted-foreground")}>
                {size}
              </button>
            ))}
          </span>
        ) : null}
        {versions.length > 0 ? (
          <select aria-label={t("image.review.version", { defaultValue: "Version" })} value={activeVersionId ?? ""}
            onChange={(event) => {
              setActiveVersionId(event.target.value || null);
              setShowCompare(true);
            }}
            className="rounded border border-border/60 bg-background px-1 py-0.5 text-xs">
            <option value="">{t("image.review.original", { defaultValue: "Original" })}</option>
            {versions.map((version) => (
              <option key={version.id} value={version.id}>
                {`${new Date(version.created_at).toLocaleTimeString()} · ${version.width}×${version.height}`}
              </option>
            ))}
          </select>
        ) : null}
        {activeVersion ? (
          <button type="button" disabled={saving} onClick={() => void saveVersion()}
            className="rounded px-2 py-1 text-muted-foreground disabled:opacity-40">
            {saving
              ? t("image.review.saving", { defaultValue: "Saving..." })
              : t("image.review.saveToWorkspace", { defaultValue: "Save to workspace" })}
          </button>
        ) : null}
        {activeVersion ? (
          <button type="button" onClick={() => setShowCompare((value) => !value)}
            className="rounded px-2 py-1 text-muted-foreground">
            {showCompare
              ? t("image.review.markUp", { defaultValue: "Mark up" })
              : t("image.review.compare", { defaultValue: "Compare" })}
          </button>
        ) : null}
        <button type="button" onClick={() => void refreshVersions()} className="rounded px-2 py-1 text-muted-foreground">
          {t("image.review.refresh", { defaultValue: "Refresh versions" })}
        </button>
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
        <button type="button" disabled={selected === null || lockedIds.has(selected)} onClick={removeSelected}
          className="rounded px-2 py-1 text-muted-foreground disabled:opacity-40">
          {t("image.review.deleteSelected", { defaultValue: "Delete region" })}
        </button>
        <label className="ml-auto flex items-center gap-1 text-muted-foreground">
          <input type="checkbox" checked={doc.compositeToOriginal}
            onChange={(event) => apply((current) => setCompositeToOriginal(current, event.target.checked))} />
          {t("image.review.onlyInside", { defaultValue: "Change only inside the marked areas" })}
        </label>
      </div>

      <div className="flex min-h-0 flex-1 flex-col lg:flex-row">
        <div ref={containerRef} className="relative min-h-[240px] min-w-0 flex-1 bg-muted/30">
          {comparing && versionSrc ? (
            <div className="flex h-full min-h-[240px] flex-col" data-testid="image-compare">
              <div className="relative flex min-h-0 flex-1 items-center justify-center overflow-hidden">
                <img src={src} alt={t("image.review.before", { defaultValue: "Before" })}
                  className="max-h-full max-w-full object-contain" />
                <img src={versionSrc} alt={t("image.review.after", { defaultValue: "After" })}
                  className="absolute inset-0 m-auto max-h-full max-w-full object-contain"
                  style={{ clipPath: `inset(0 0 0 ${comparePosition}%)` }} />
              </div>
              <label className="flex items-center gap-2 px-3 py-2 text-xs text-muted-foreground">
                {t("image.review.before", { defaultValue: "Before" })}
                <input type="range" min={0} max={100} value={comparePosition} className="flex-1"
                  aria-label={t("image.review.compare", { defaultValue: "Compare before and after" })}
                  onChange={(event) => setComparePosition(Number(event.target.value))} />
                {t("image.review.after", { defaultValue: "After" })}
              </label>
            </div>
          ) : image ? (
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
              onMouseDown={onStageDown}
              onTouchStart={onStageDown}
              onMouseMove={onStageMove}
              onTouchMove={onStageMove}
              onMouseUp={onStageUp}
              onTouchEnd={onStageUp}
            >
              <Layer>
                <KonvaImage image={image} width={displayWidth} height={displayHeight} />
                {doc.regions.map((region) => renderShape(region))}
                {doc.regions.map((region) => renderHandles(region))}
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
                    <Text key={`label-${region.id}`} x={anchor[0] + 4 / zoom} y={anchor[1] + 4 / zoom}
                      text={String(region.id)} fontSize={14 / zoom} fontStyle="bold" fill={colorOf(region)} listening={false} />
                  );
                })}
                {draft && draft.shape === "rect" ? (
                  <Rect x={Math.min(draft.start[0], draft.current[0]) * displayWidth}
                    y={Math.min(draft.start[1], draft.current[1]) * displayHeight}
                    width={Math.abs(draft.current[0] - draft.start[0]) * displayWidth}
                    height={Math.abs(draft.current[1] - draft.start[1]) * displayHeight}
                    stroke="#111827" dash={dash} strokeWidth={1.5 / zoom} listening={false} />
                ) : null}
                {draft && draft.shape === "ellipse" ? (
                  <Ellipse x={((draft.start[0] + draft.current[0]) / 2) * displayWidth}
                    y={((draft.start[1] + draft.current[1]) / 2) * displayHeight}
                    radiusX={(Math.abs(draft.current[0] - draft.start[0]) * displayWidth) / 2}
                    radiusY={(Math.abs(draft.current[1] - draft.start[1]) * displayHeight) / 2}
                    stroke="#111827" dash={dash} strokeWidth={1.5 / zoom} listening={false} />
                ) : null}
                {draft && draft.shape === "brush" ? (
                  <Line points={draft.points.flatMap(([x, y]) => [x * displayWidth, y * displayHeight])}
                    stroke={draft.erase ? ERASER_COLOR : "#111827"} opacity={0.3}
                    strokeWidth={2 * draft.radius * shorter} lineCap="round" lineJoin="round" listening={false} />
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
          {tree.length > 1 ? (
            <nav aria-label={t("image.review.tree", { defaultValue: "Versions of this image" })} className="flex flex-col gap-0.5 text-xs">
              {tree.map((row) => (
                <button key={row.path} type="button" aria-current={row.path === path ? "true" : undefined}
                  onClick={() => onOpenImage?.(row.path)} disabled={!onOpenImage}
                  style={{ paddingLeft: `${0.5 + row.depth * 0.75}rem` }}
                  className={cn("rounded py-1 pr-2 text-left disabled:opacity-100",
                    row.path === path ? "bg-muted font-medium" : "text-muted-foreground hover:bg-muted/60")}>
                  {row.label}
                </button>
              ))}
            </nav>
          ) : null}
          {savedAs ? (
            <p role="status" className="text-xs text-muted-foreground">
              {t("image.review.savedAs", { defaultValue: "Saved as {{path}}", path: savedAs })}
            </p>
          ) : null}
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
                <span className="font-medium" style={{ color: colorOf(region) }}>{regionLabel(region)}</span>
                {reportById.get(region.id) ? (
                  <span className={cn("rounded px-1.5 py-0.5 text-[10px]", STATUS_STYLE[reportById.get(region.id)?.status ?? "not_done"])}>
                    {STATUS_LABEL[reportById.get(region.id)?.status ?? "not_done"]}
                  </span>
                ) : null}
                <button type="button" className="text-muted-foreground underline"
                  disabled={lockedIds.has(region.id)}
                  onClick={() => apply((current) => removeRegion(current, region.id))}>
                  {t("image.review.remove", { defaultValue: "Remove" })}
                </button>
              </div>
              <textarea aria-label={t("image.review.noteFor", { defaultValue: "Note for region {{id}}", id: region.id })}
                className="min-h-[44px] w-full rounded border border-border/60 bg-background p-1.5 text-sm text-foreground"
                value={drafts[region.id] ?? region.note}
                onChange={(event) => setDrafts((current) => ({ ...current, [region.id]: event.target.value }))}
                disabled={lockedIds.has(region.id)}
                onBlur={() => commitNote(region.id)} />
              {reportById.get(region.id) ? (
                <p className="mt-1 text-[11px] text-muted-foreground">
                  {reportById.get(region.id)?.reason}
                  {lockedIds.has(region.id)
                    ? ` · ${t("image.review.locked", { defaultValue: "Done: kept as it is" })}`
                    : ""}
                </p>
              ) : null}
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
              : resendMode
                ? t("image.review.resend", { defaultValue: "Resend the regions not done" })
                : t("image.review.send", { defaultValue: "Send edits" })}
          </button>
        </aside>
      </div>
    </div>
  );
}

export default ImageReviewPane;

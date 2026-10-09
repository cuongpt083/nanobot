import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { MarkdownText } from "@/components/MarkdownText";
import { MonacoEditor } from "@/components/workspace/MonacoEditor";
import { ChangeReview } from "@/components/workspace/ChangeReview";
import { WorkspaceTree } from "@/components/workspace/WorkspaceTree";
import {
  isWorkspaceConflict,
  listStagedChanges,
  readWorkspaceFile,
  saveWorkspaceFile,
  setWorkspaceOpenTabs,
  type StagedChange,
  type WebUIMutationTransport,
} from "@/lib/api";
import { useThemeValue } from "@/hooks/useTheme";
import { cn } from "@/lib/utils";

/** How long the markdown preview waits after the last keystroke before re-rendering. */
export const PREVIEW_DEBOUNCE_MS = 300;

interface Buffer {
  path: string;
  language: string;
  text: string;
  /** Text as it was last loaded or saved; ``text !== savedText`` means unsaved changes. */
  savedText: string;
  /** Version the next save is based on; ``null`` for a file that does not exist yet. */
  version: string | null;
  conflict: boolean;
  error: string | null;
}

interface WorkspaceEditorProps {
  sessionKey: string;
  token: string;
  client: WebUIMutationTransport;
  initialPath: string;
  base?: string;
}

function languageOf(path: string): string {
  const name = path.split("/").pop()?.toLowerCase() ?? "";
  if (name === "dockerfile") return "dockerfile";
  const ext = name.includes(".") ? name.split(".").pop() ?? "" : "";
  if (ext === "md" || ext === "mdx") return "markdown";
  return ext || "text";
}

/**
 * ``value`` settled after ``delay`` ms, except when ``resetKey`` changes (another file opened):
 * then the new value shows at once instead of the previous file's text for a moment.
 */
function useDebounced<T>(value: T, delay: number, resetKey: string): T {
  const [settled, setSettled] = useState({ key: resetKey, value });
  useEffect(() => {
    if (settled.key !== resetKey) {
      setSettled({ key: resetKey, value });
      return;
    }
    const timer = window.setTimeout(() => setSettled({ key: resetKey, value }), delay);
    return () => window.clearTimeout(timer);
  }, [value, delay, resetKey, settled.key]);
  return settled.key === resetKey ? settled.value : value;
}

/**
 * Edit project files in a Monaco pane with a folder tree, tabs, and (for markdown) a live preview.
 * Saves carry the version the file was opened at; a save against a file changed on disk is refused
 * and the user chooses between reloading and keeping their own text.
 */
export function WorkspaceEditor({ sessionKey, token, client, initialPath, base = "" }: WorkspaceEditorProps) {
  const { t } = useTranslation();
  const dark = useThemeValue() === "dark";
  const [buffers, setBuffers] = useState<Buffer[]>([]);
  const [activePath, setActivePath] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [previewOn, setPreviewOn] = useState(true);
  const [changes, setChanges] = useState<StagedChange[]>([]);
  const [reviewing, setReviewing] = useState<StagedChange | null>(null);
  const openedRef = useRef(new Set<string>());
  // Callbacks registered once (the editor's save command) read the latest buffers through this ref.
  const buffersRef = useRef(buffers);
  buffersRef.current = buffers;

  const active = useMemo(
    () => buffers.find((buffer) => buffer.path === activePath) ?? null,
    [buffers, activePath],
  );
  const debouncedText = useDebounced(active?.text ?? "", PREVIEW_DEBOUNCE_MS, active?.path ?? "");

  const patch = useCallback((path: string, change: Partial<Buffer>) => {
    setBuffers((current) => current.map((b) => (b.path === path ? { ...b, ...change } : b)));
  }, []);

  const open = useCallback(async (path: string) => {
    setNotice(null);
    if (openedRef.current.has(path)) {
      setActivePath(path);
      return;
    }
    try {
      const file = await readWorkspaceFile(token, sessionKey, path, base);
      openedRef.current.add(path);
      setBuffers((current) => [
        ...current,
        {
          path,
          language: languageOf(path),
          text: file.content,
          savedText: file.content,
          version: file.version,
          conflict: false,
          error: null,
        },
      ]);
      setActivePath(path);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : t("workspace.openFailed", { defaultValue: "Could not open the file" }));
    }
  }, [base, sessionKey, t, token]);

  const refreshChanges = useCallback(async () => {
    try {
      setChanges(await listStagedChanges(token, sessionKey, base));
    } catch {
      // The change list is a convenience; the editor works without it.
    }
  }, [base, sessionKey, token]);

  useEffect(() => {
    void refreshChanges();
  }, [refreshChanges]);

  // The gateway needs the open tabs so an agent write to them is reviewed rather than made directly.
  const openPathsKey = buffers.map((b) => b.path).join("\n");
  useEffect(() => {
    const paths = openPathsKey ? openPathsKey.split("\n") : [];
    void setWorkspaceOpenTabs(client, sessionKey, paths).catch(() => undefined);
  }, [client, openPathsKey, sessionKey]);

  useEffect(() => {
    void open(initialPath);
    // Only the file that was requested opens on mount; later opens come from the tree.
  }, [initialPath]);

  /** Save the buffer. ``baseVersion`` overrides the loaded version (used after a conflict is resolved). */
  const save = useCallback(async (path: string, baseVersion?: string | null) => {
    const buffer = buffersRef.current.find((b) => b.path === path);
    if (!buffer) return;
    try {
      const saved = await saveWorkspaceFile(client, sessionKey, {
        path,
        content: buffer.text,
        baseVersion: baseVersion === undefined ? buffer.version : baseVersion,
      });
      patch(path, { savedText: buffer.text, version: saved.version, conflict: false, error: null });
    } catch (error) {
      if (isWorkspaceConflict(error)) {
        patch(path, { conflict: true });
      } else {
        patch(path, { error: error instanceof Error ? error.message : "Save failed" });
      }
    }
  }, [client, patch, sessionKey]);

  const reload = async (path: string) => {
    try {
      const file = await readWorkspaceFile(token, sessionKey, path, base);
      patch(path, { text: file.content, savedText: file.content, version: file.version, conflict: false, error: null });
    } catch (error) {
      patch(path, { error: error instanceof Error ? error.message : "Could not reload the file" });
    }
  };

  const keepMine = async (path: string) => {
    try {
      const current = await readWorkspaceFile(token, sessionKey, path, base);
      patch(path, { version: current.version, conflict: false });
      await save(path, current.version);
    } catch (error) {
      patch(path, { error: error instanceof Error ? error.message : "Could not read the current version" });
    }
  };

  const close = (path: string) => {
    const buffer = buffersRef.current.find((b) => b.path === path);
    if (buffer && buffer.text !== buffer.savedText && !window.confirm("Close without saving your changes?")) {
      return;
    }
    openedRef.current.delete(path);
    setBuffers((current) => current.filter((b) => b.path !== path));
    setActivePath((current) => {
      if (current !== path) return current;
      const remaining = buffersRef.current.filter((b) => b.path !== path);
      return remaining.length ? remaining[remaining.length - 1].path : null;
    });
  };

  const onRenamed = (from: string, to: string) => {
    openedRef.current.delete(from);
    openedRef.current.add(to);
    setBuffers((current) => current.map((b) => (b.path === from ? { ...b, path: to, language: languageOf(to) } : b)));
    setActivePath((current) => (current === from ? to : current));
  };

  const onDeleted = (path: string) => {
    openedRef.current.delete(path);
    setBuffers((current) => current.filter((b) => b.path !== path));
    setActivePath((current) => (current === path ? null : current));
  };

  /** After a decision: an accepted change to an open, clean file is reloaded; to a dirty one, the conflict banner shows. */
  const onDecided = (change: StagedChange, action: "accept" | "reject") => {
    setReviewing(null);
    setNotice(null);
    void refreshChanges();
    if (action !== "accept") return;
    const buffer = buffersRef.current.find((b) => b.path === change.path);
    if (!buffer) return;
    if (buffer.text === buffer.savedText) void reload(change.path);
    else patch(change.path, { conflict: true });
  };

  const isMarkdown = active?.language === "markdown";
  const dirty = active ? active.text !== active.savedText : false;

  return (
    <div className="flex h-full min-h-0 flex-col" data-testid="workspace-editor">
      <div className="flex min-h-0 flex-1">
        <aside className="w-56 shrink-0 border-r border-border/50">
          <WorkspaceTree
            sessionKey={sessionKey}
            token={token}
            client={client}
            base={base}
            activePath={activePath}
            onOpen={(path) => void open(path)}
            onRenamed={onRenamed}
            onDeleted={onDeleted}
            onError={(message) => setNotice(message)}
          />
        </aside>

        <section className="flex min-w-0 flex-1 flex-col">
          <div role="tablist" className="flex items-center gap-1 overflow-x-auto border-b border-border/50 px-1">
            {buffers.map((buffer) => {
              const isDirty = buffer.text !== buffer.savedText;
              return (
                <div key={buffer.path} className={cn(
                  "flex items-center gap-1 rounded-t px-2 py-1 text-xs",
                  buffer.path === activePath ? "bg-muted font-medium" : "text-muted-foreground",
                )}>
                  <button type="button" role="tab" aria-selected={buffer.path === activePath}
                    className="max-w-[160px] truncate" onClick={() => setActivePath(buffer.path)}>
                    {buffer.path.split("/").pop()}{isDirty ? " •" : ""}
                  </button>
                  <button type="button" aria-label={`Close ${buffer.path}`} onClick={() => close(buffer.path)}>
                    ×
                  </button>
                </div>
              );
            })}
            {changes.length > 0 ? (
              <button type="button" className="ml-auto px-2 text-xs font-medium text-amber-700 dark:text-amber-200"
                onClick={() => setReviewing(reviewing ? null : changes[0])}>
                {t("workspace.changesPending", { defaultValue: "{{count}} proposed change(s)", count: changes.length })}
              </button>
            ) : null}
            {isMarkdown ? (
              <button type="button" className="ml-auto px-2 text-xs text-muted-foreground"
                onClick={() => setPreviewOn((value) => !value)}>
                {previewOn
                  ? t("workspace.hidePreview", { defaultValue: "Hide preview" })
                  : t("workspace.showPreview", { defaultValue: "Show preview" })}
              </button>
            ) : null}
          </div>

          {active?.conflict ? (
            <div role="alert" className="flex flex-wrap items-center gap-2 border-b border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs">
              <span>
                {t("workspace.conflict", { defaultValue: "This file changed on disk since you opened it." })}
              </span>
              <button type="button" className="underline" onClick={() => void reload(active.path)}>
                {t("workspace.reload", { defaultValue: "Reload from disk" })}
              </button>
              <button type="button" className="underline" onClick={() => void keepMine(active.path)}>
                {t("workspace.keepMine", { defaultValue: "Keep my version" })}
              </button>
            </div>
          ) : null}
          {notice || active?.error ? (
            <div role="status" className="border-b border-border/50 px-3 py-1.5 text-xs text-red-600 dark:text-red-300">
              {active?.error ?? notice}
            </div>
          ) : null}

          {reviewing ? (
            <div className="flex min-h-0 flex-1 flex-col">
              {changes.length > 1 ? (
                <div className="flex gap-1 overflow-x-auto border-b border-border/50 px-2 py-1 text-xs">
                  {changes.map((change) => (
                    <button key={change.id} type="button" onClick={() => setReviewing(change)}
                      className={cn("rounded px-2 py-0.5", change.id === reviewing.id ? "bg-muted font-medium" : "text-muted-foreground")}>
                      {change.path}
                    </button>
                  ))}
                </div>
              ) : null}
              <ChangeReview
                key={reviewing.id}
                change={reviewing}
                sessionKey={sessionKey}
                token={token}
                client={client}
                base={base}
                onDecided={onDecided}
              />
            </div>
          ) : (
          <div className="flex min-h-0 flex-1">
            {active ? (
              <>
                <div className={cn("min-w-0 flex-1", isMarkdown && previewOn && "border-r border-border/50")}>
                  <MonacoEditor
                    key={active.path}
                    value={active.text}
                    language={active.language}
                    dark={dark}
                    onChange={(text) => patch(active.path, { text })}
                    onSave={() => void save(active.path)}
                  />
                </div>
                {isMarkdown && previewOn ? (
                  <div className="min-w-0 flex-1 overflow-auto p-3">
                    <MarkdownText>{debouncedText}</MarkdownText>
                  </div>
                ) : null}
              </>
            ) : (
              <p className="p-4 text-sm text-muted-foreground">
                {t("workspace.pickFile", { defaultValue: "Open a file from the tree." })}
              </p>
            )}
          </div>
          )}

          <div className="flex items-center justify-between border-t border-border/50 px-3 py-1 text-[11px] text-muted-foreground">
            <span>{active?.path ?? ""}</span>
            <span>{dirty ? t("workspace.unsaved", { defaultValue: "Unsaved" }) : t("workspace.saved", { defaultValue: "Saved" })}</span>
            <span>{t("workspace.saveHint", { defaultValue: "Ctrl+S to save" })}</span>
          </div>
        </section>
      </div>
    </div>
  );
}

export default WorkspaceEditor;

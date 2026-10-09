import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { DiffView } from "@/components/workspace/DiffView";
import { assemble, diffHunks } from "@/components/workspace/hunks";
import {
  ApiError,
  readWorkspaceFile,
  resolveStagedChange,
  type StagedChange,
  type WebUIMutationTransport,
} from "@/lib/api";
import { useThemeValue } from "@/hooks/useTheme";

interface ChangeReviewProps {
  change: StagedChange;
  sessionKey: string;
  token: string;
  client: WebUIMutationTransport;
  base?: string;
  onDecided: (change: StagedChange, action: "accept" | "reject") => void;
}

/** A proposed change against the file on disk, with accept and reject. Nothing is written until accept. */
export function ChangeReview({ change, sessionKey, token, client, base = "", onDecided }: ChangeReviewProps) {
  const { t } = useTranslation();
  const dark = useThemeValue() === "dark";
  const [original, setOriginal] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Hunks the user has turned off; every hunk is kept by default, so accepting is the same as before.
  const [dropped, setDropped] = useState<Set<number>>(new Set());
  const hunks = useMemo(
    () => (original === null ? [] : diffHunks(original, change.content)),
    [original, change.content],
  );
  const keptCount = hunks.length - hunks.filter((hunk) => dropped.has(hunk.id)).length;
  const partial = dropped.size > 0;

  useEffect(() => {
    let cancelled = false;
    setOriginal(null);
    readWorkspaceFile(token, sessionKey, change.path, base)
      .then((file) => {
        if (!cancelled) setOriginal(file.content);
      })
      .catch(() => {
        // Missing on disk (a proposal for a new file) or unreadable: compare against nothing.
        if (!cancelled) setOriginal("");
      });
    return () => {
      cancelled = true;
    };
  }, [base, change.path, change.id, sessionKey, token]);

  const decide = async (action: "accept" | "reject") => {
    setBusy(true);
    setError(null);
    try {
      // Accepting part of a proposal writes the text assembled from the hunks that are kept.
      const content = action === "accept" && partial && original !== null
        ? assemble(original, hunks, new Set(hunks.filter((hunk) => !dropped.has(hunk.id)).map((hunk) => hunk.id)))
        : undefined;
      if (content === undefined) await resolveStagedChange(client, sessionKey, change.id, action);
      else await resolveStagedChange(client, sessionKey, change.id, action, content);
      onDecided(change, action);
    } catch (reason) {
      if (reason instanceof ApiError && reason.status === 409) {
        setError(t("workspace.staleChange", {
          defaultValue: "The file changed after the agent read it. Reject this proposal and ask the agent to read it again.",
        }));
      } else {
        setError(reason instanceof Error ? reason.message : "The change could not be applied");
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex h-full min-h-0 flex-col" data-testid="change-review">
      <div className="flex flex-wrap items-center gap-2 border-b border-border/50 px-3 py-2 text-xs">
        <span className="font-medium">{change.path}</span>
        <span className="text-muted-foreground">
          {t("workspace.proposedBy", { defaultValue: "Proposed by {{by}}", by: change.by })}
        </span>
        {change.stale ? (
          <span className="rounded bg-amber-500/15 px-1.5 py-0.5 text-amber-700 dark:text-amber-200">
            {t("workspace.stale", { defaultValue: "file changed since" })}
          </span>
        ) : null}
        <span className="ml-auto flex gap-1">
          <button type="button" disabled={busy || change.stale || (hunks.length > 0 && keptCount === 0)}
            onClick={() => void decide("accept")}
            className="rounded px-2 py-1 bg-emerald-600 text-white disabled:opacity-50">
            {partial
              ? t("workspace.acceptSelected", { defaultValue: "Accept {{kept}} of {{total}} changes", kept: keptCount, total: hunks.length })
              : t("workspace.accept", { defaultValue: "Accept" })}
          </button>
          <button type="button" disabled={busy} onClick={() => void decide("reject")}
            className="rounded border border-border px-2 py-1 disabled:opacity-50">
            {t("workspace.reject", { defaultValue: "Reject" })}
          </button>
        </span>
      </div>
      {error ? <div role="alert" className="border-b border-red-500/25 bg-red-500/10 px-3 py-1.5 text-xs text-red-600 dark:text-red-300">{error}</div> : null}
      {hunks.length > 0 ? (
        <ul aria-label={t("workspace.hunks", { defaultValue: "Changes in this proposal" })}
          className="max-h-40 space-y-1 overflow-auto border-b border-border/50 px-3 py-2 text-xs">
          {hunks.map((hunk) => {
            const preview = (hunk.newLines[0] ?? hunk.oldLines[0] ?? "").slice(0, 80);
            return (
              <li key={hunk.id} className="flex items-start gap-2">
                <input type="checkbox" className="mt-0.5" checked={!dropped.has(hunk.id)}
                  aria-label={t("workspace.keepChange", { defaultValue: "Keep change at line {{line}}", line: hunk.start + 1 })}
                  onChange={(event) => setDropped((current) => {
                    const next = new Set(current);
                    if (event.target.checked) next.delete(hunk.id);
                    else next.add(hunk.id);
                    return next;
                  })} />
                <span className="text-muted-foreground">
                  {t("workspace.lineAt", { defaultValue: "line {{line}}", line: hunk.start + 1 })}
                  {" · "}
                  {hunk.oldLines.length > 0 ? `−${hunk.oldLines.length} ` : ""}
                  {hunk.newLines.length > 0 ? `+${hunk.newLines.length} ` : ""}
                  <code className="font-mono">{preview}</code>
                </span>
              </li>
            );
          })}
        </ul>
      ) : null}
      <div className="min-h-0 flex-1">
        {original === null ? (
          <p className="p-4 text-sm text-muted-foreground">{t("workspace.loadingDiff", { defaultValue: "Loading..." })}</p>
        ) : (
          <DiffView original={original} modified={change.content} language={languageOf(change.path)} dark={dark} />
        )}
      </div>
    </div>
  );
}

function languageOf(path: string): string {
  const name = path.split("/").pop()?.toLowerCase() ?? "";
  const ext = name.includes(".") ? name.split(".").pop() ?? "" : "";
  if (ext === "md" || ext === "mdx") return "markdown";
  return ext || "text";
}

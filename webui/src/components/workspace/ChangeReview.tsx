import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { DiffView } from "@/components/workspace/DiffView";
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
      await resolveStagedChange(client, sessionKey, change.id, action);
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
          <button type="button" disabled={busy || change.stale} onClick={() => void decide("accept")}
            className="rounded px-2 py-1 bg-emerald-600 text-white disabled:opacity-50">
            {t("workspace.accept", { defaultValue: "Accept" })}
          </button>
          <button type="button" disabled={busy} onClick={() => void decide("reject")}
            className="rounded border border-border px-2 py-1 disabled:opacity-50">
            {t("workspace.reject", { defaultValue: "Reject" })}
          </button>
        </span>
      </div>
      {error ? <div role="alert" className="border-b border-red-500/25 bg-red-500/10 px-3 py-1.5 text-xs text-red-600 dark:text-red-300">{error}</div> : null}
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

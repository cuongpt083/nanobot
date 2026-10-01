import { FolderOpen, GitBranch } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import {
  AlertDialog,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { setCoworkerCoding, type WebUIMutationTransport } from "@/lib/api";
import type { CoworkerCodingSwitch, CoworkerInitPreview, CoworkerStatus } from "@/lib/types";

interface CoworkerDirectConfirmProps {
  client: WebUIMutationTransport;
  sessionKey: string;
  status: CoworkerStatus | null;
  onStatus: (status: CoworkerStatus) => void;
}

/**
 * Asks the user how the coding agent may work on a project that is not a git repository: edit its
 * files in place, or first turn it into a repository (after reviewing exactly what is committed).
 * The question is raised by the backend (`coding.project.pending_direct`); the answer comes only
 * from here (or `/code direct allow`, `/code init`), never from the model.
 */
export function CoworkerDirectConfirm({
  client,
  sessionKey,
  status,
  onStatus,
}: CoworkerDirectConfirmProps) {
  const { t } = useTranslation();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const project = status?.coding?.project;
  const path = project?.path ?? null;
  const preview = project?.init_preview ?? null;
  const open = Boolean((project?.pending_direct || preview) && path);

  const send = async (change: CoworkerCodingSwitch) => {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      onStatus(await setCoworkerCoding(client, sessionKey, change));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(false);
    }
  };

  const answer = (allow: boolean) => (path ? send({ direct_ok: allow, path }) : undefined);
  const init = (action: "preview" | "confirm" | "cancel") =>
    path ? send({ init: action, path }) : undefined;

  if (!open || !path) return null;

  return (
    <AlertDialog
      open={open}
      onOpenChange={(next) => {
        if (next) return;
        void (preview ? init("cancel") : answer(false));
      }}
    >
      <AlertDialogContent data-testid="direct-confirm" className="max-w-md">
        {preview ? (
          <InitReview
            preview={preview}
            error={error}
            busy={busy}
            onBack={() => void init("cancel")}
            onConfirm={() => void init("confirm")}
          />
        ) : (
          <>
            <AlertDialogHeader>
              <AlertDialogTitle className="flex items-center gap-2">
                <FolderOpen className="h-4 w-4 text-primary" aria-hidden />
                {t("coworker.directConfirm.title", {
                  defaultValue: "Let the coding agent edit this folder?",
                })}
              </AlertDialogTitle>
              <AlertDialogDescription asChild>
                <div className="space-y-2 text-left text-[13px]">
                  <p className="break-all font-mono text-[12px] text-foreground">{path}</p>
                  <p>
                    {t("coworker.directConfirm.body", {
                      defaultValue:
                        "This folder is not a git repository, so the coding agent will change its files in place. A snapshot is taken first so the changes can be undone.",
                    })}
                  </p>
                  <p>
                    {t("coworker.directConfirm.warning", {
                      defaultValue:
                        "The coding tool is not limited by this chat's workspace restriction and can change or delete files in this folder.",
                    })}
                  </p>
                  {error ? (
                    <p role="alert" className="text-red-600 dark:text-red-400">
                      {error}
                    </p>
                  ) : null}
                </div>
              </AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter className="gap-2 sm:flex-wrap">
              <Button type="button" variant="outline" disabled={busy} onClick={() => void answer(false)}>
                {t("coworker.directConfirm.deny", { defaultValue: "Not now" })}
              </Button>
              <Button
                type="button"
                variant="outline"
                data-testid="direct-confirm-init"
                disabled={busy}
                onClick={() => void init("preview")}
              >
                <GitBranch className="mr-1 h-3.5 w-3.5" aria-hidden />
                {t("coworker.directConfirm.init", { defaultValue: "Initialize git instead…" })}
              </Button>
              <Button
                type="button"
                data-testid="direct-confirm-allow"
                disabled={busy}
                onClick={() => void answer(true)}
              >
                {t("coworker.directConfirm.allow", { defaultValue: "Allow editing in place" })}
              </Button>
            </AlertDialogFooter>
          </>
        )}
      </AlertDialogContent>
    </AlertDialog>
  );
}

function LeftOut({ label, items }: { label: string; items: string[] }) {
  if (items.length === 0) return null;
  return (
    <p className="text-[12px]">
      <span className="font-medium text-foreground">{label}</span>{" "}
      <span className="break-all font-mono">{items.join(", ")}</span>
    </p>
  );
}

function InitReview({
  preview,
  error,
  busy,
  onBack,
  onConfirm,
}: {
  preview: CoworkerInitPreview;
  error: string | null;
  busy: boolean;
  onBack: () => void;
  onConfirm: () => void;
}) {
  const { t } = useTranslation();
  const more = preview.file_count - preview.files.length;
  return (
    <>
      <AlertDialogHeader>
        <AlertDialogTitle className="flex items-center gap-2">
          <GitBranch className="h-4 w-4 text-primary" aria-hidden />
          {t("coworker.directConfirm.initTitle", { defaultValue: "Create a git repository?" })}
        </AlertDialogTitle>
        <AlertDialogDescription asChild>
          <div className="space-y-2 text-left text-[13px]" data-testid="init-review">
            <p className="break-all font-mono text-[12px] text-foreground">{preview.path}</p>
            <p>
              {t("coworker.directConfirm.initBody", {
                count: preview.file_count,
                size: preview.total_mb,
                defaultValue:
                  "The first commit will contain {{count}} file(s), about {{size}} MB. Nothing is changed until you confirm.",
              })}
            </p>
            <ul
              data-testid="init-files"
              className="max-h-40 overflow-y-auto rounded-md border border-border/60 bg-muted/30 p-2 font-mono text-[11px]"
            >
              {preview.files.map((file) => (
                <li key={file} className="truncate">
                  {file}
                </li>
              ))}
              {more > 0 ? (
                <li className="text-muted-foreground">
                  {t("coworker.coding.moreFiles", { count: more, defaultValue: "… and {{count}} more" })}
                </li>
              ) : null}
            </ul>
            {preview.gitignore ? (
              <details className="text-[12px]">
                <summary className="cursor-pointer font-medium text-foreground">
                  {t("coworker.directConfirm.initIgnore", {
                    defaultValue: "A new .gitignore will be created",
                  })}
                </summary>
                <pre
                  data-testid="init-gitignore"
                  className="mt-1 max-h-28 overflow-auto rounded-md bg-muted/30 p-2 font-mono text-[11px]"
                >
                  {preview.gitignore}
                </pre>
              </details>
            ) : (
              <p className="text-[12px]">
                {t("coworker.directConfirm.initKeepIgnore", {
                  defaultValue: "Your existing .gitignore is kept.",
                })}
              </p>
            )}
            <LeftOut
              label={t("coworker.directConfirm.initSecrets", { defaultValue: "Left out (looks like secrets):" })}
              items={preview.skipped_sensitive}
            />
            <LeftOut
              label={t("coworker.directConfirm.initLarge", { defaultValue: "Left out (over 20 MB):" })}
              items={preview.skipped_large}
            />
            <LeftOut
              label={t("coworker.directConfirm.initEmbedded", { defaultValue: "Left out (separate git repositories):" })}
              items={preview.skipped_embedded}
            />
            {error ? (
              <p role="alert" className="text-red-600 dark:text-red-400">
                {error}
              </p>
            ) : null}
          </div>
        </AlertDialogDescription>
      </AlertDialogHeader>
      <AlertDialogFooter>
        <Button type="button" variant="outline" disabled={busy} onClick={onBack}>
          {t("coworker.directConfirm.initBack", { defaultValue: "Back" })}
        </Button>
        <Button type="button" data-testid="init-confirm" disabled={busy} onClick={onConfirm}>
          {t("coworker.directConfirm.initConfirm", { defaultValue: "Create repository and commit" })}
        </Button>
      </AlertDialogFooter>
    </>
  );
}

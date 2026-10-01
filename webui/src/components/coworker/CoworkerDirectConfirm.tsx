import { FolderOpen } from "lucide-react";
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
import type { CoworkerStatus } from "@/lib/types";

interface CoworkerDirectConfirmProps {
  client: WebUIMutationTransport;
  sessionKey: string;
  status: CoworkerStatus | null;
  onStatus: (status: CoworkerStatus) => void;
}

/**
 * Asks the user whether the coding agent may edit a non-git project in place. The question is
 * raised by the backend (`coding.project.pending_direct`); the answer comes only from here (or
 * `/code direct allow`), never from the model.
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
  const open = Boolean(project?.pending_direct && path);

  const answer = async (allow: boolean) => {
    if (!path || busy) return;
    setBusy(true);
    setError(null);
    try {
      onStatus(await setCoworkerCoding(client, sessionKey, { direct_ok: allow, path }));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(false);
    }
  };

  if (!open || !path) return null;

  return (
    <AlertDialog open={open} onOpenChange={(next) => (!next ? void answer(false) : undefined)}>
      <AlertDialogContent data-testid="direct-confirm" className="max-w-md">
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
        <AlertDialogFooter>
          <Button
            type="button"
            variant="outline"
            disabled={busy}
            onClick={() => void answer(false)}
          >
            {t("coworker.directConfirm.deny", { defaultValue: "Not now" })}
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
      </AlertDialogContent>
    </AlertDialog>
  );
}

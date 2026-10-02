import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { AlertTriangle, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import type { OAuthStatusEvent } from "@/lib/nanobot-client";
import { useClient } from "@/providers/ClientProvider";

/** How long the "token refreshed" toast stays up. */
const REFRESHED_TOAST_MS = 4_000;

function providerLabel(provider: string): string {
  if (provider === "anthropic_oauth") return "Anthropic (OAuth)";
  return provider;
}

/** App-level notices for OAuth token status: a transient refresh toast and a
 *  persistent, dismissible "sign in again" banner. Fed by the server's
 *  ``oauth_status_updated`` event, so it is not tied to any one chat. */
export function OAuthStatusNotice({ onOpenModelSettings }: { onOpenModelSettings?: () => void }) {
  const { client } = useClient();
  const { t } = useTranslation();
  const [toast, setToast] = useState<string | null>(null);
  const [reauthProvider, setReauthProvider] = useState<string | null>(null);
  const toastTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const clearToastTimer = useCallback(() => {
    if (toastTimer.current !== null) {
      clearTimeout(toastTimer.current);
      toastTimer.current = null;
    }
  }, []);

  useEffect(() => {
    const unsubscribe = client.onOAuthStatus((event: OAuthStatusEvent) => {
      if (event.status === "reauth_required") {
        clearToastTimer();
        setToast(null);
        setReauthProvider(event.provider);
        return;
      }
      // A successful refresh means the account is healthy again.
      setReauthProvider(null);
      clearToastTimer();
      setToast(
        t("settings.oauth.tokenRefreshed", {
          provider: providerLabel(event.provider),
          defaultValue: "{{provider}} access token refreshed.",
        }),
      );
      toastTimer.current = setTimeout(() => setToast(null), REFRESHED_TOAST_MS);
    });
    return () => {
      unsubscribe();
      clearToastTimer();
    };
  }, [client, t, clearToastTimer]);

  if (!toast && !reauthProvider) return null;

  return (
    <div className="fixed left-1/2 top-[calc(0.75rem+env(safe-area-inset-top))] z-50 flex w-[min(38rem,calc(100vw-1rem))] -translate-x-1/2 flex-col items-center gap-2">
      {reauthProvider ? (
        <div
          role="alert"
          aria-live="assertive"
          className="flex w-full items-start gap-2 rounded-control border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-sm text-amber-700 shadow-lg backdrop-blur dark:text-amber-300"
        >
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
          <div className="flex min-w-0 flex-1 flex-col gap-1">
            <span className="font-medium">
              {t("thread.composer.reauthNotice", {
                provider: providerLabel(reauthProvider),
                defaultValue: "{{provider}} authorization expired. Please sign in again.",
              })}
            </span>
            {onOpenModelSettings ? (
              <button
                type="button"
                onClick={onOpenModelSettings}
                className="self-start rounded-sm font-medium underline underline-offset-4 hover:no-underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                {t("thread.composer.reauthSettings", { defaultValue: "Open model settings" })}
              </button>
            ) : null}
          </div>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="h-6 w-6 shrink-0 rounded-full"
            aria-label={t("common.dismiss")}
            onClick={() => setReauthProvider(null)}
          >
            <X className="h-3.5 w-3.5" aria-hidden />
          </Button>
        </div>
      ) : null}
      {toast ? (
        <div
          role="status"
          className="max-w-full rounded-full border border-border/60 bg-card px-4 py-2 text-sm font-medium shadow-lg"
        >
          {toast}
        </div>
      ) : null}
    </div>
  );
}

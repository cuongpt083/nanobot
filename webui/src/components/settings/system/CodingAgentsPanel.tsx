import { Code2, Loader2 } from "lucide-react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { StatusPill } from "@/components/settings/shared/SettingsControls";
import { Button } from "@/components/ui/button";
import { fetchCoworkerSettings } from "@/lib/api";
import type { CoworkerBackendDetection, CoworkerSettingsPayload } from "@/lib/types";
import { useClient } from "@/providers/ClientProvider";

const BACKENDS = [
  {
    name: "pi" as const,
    title: "Pi",
    blurb: "Lean, steerable coding harness (JSONL RPC). Log in inside Pi.",
    badges: ["Git worktree", "Live steering"],
  },
];

function stateLabel(
  info: CoworkerBackendDetection | undefined,
  tx: (key: string, fallback: string) => string,
): string {
  if (!info?.found) return tx("coding.notFound", "not found");
  if (info.custom) return tx("coding.custom", "custom command");
  return info.version ?? tx("coding.installed", "installed");
}

/** Read-only Pi card for the Apps page; editing happens in Settings → Coworker. */
export function CodingAgentsPanel({ onConfigure }: { onConfigure?: () => void }) {
  const { t } = useTranslation();
  const { token } = useClient();
  const tx = (key: string, fallback: string) => t(`coworker.settings.${key}`, { defaultValue: fallback });
  const [payload, setPayload] = useState<CoworkerSettingsPayload | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetchCoworkerSettings(token)
      .then((next) => {
        if (!cancelled) setPayload(next);
      })
      .catch((reason: unknown) => {
        if (!cancelled) setError(reason instanceof Error ? reason.message : "Could not load coding agents.");
      });
    return () => {
      cancelled = true;
    };
  }, [token]);

  const coding = payload?.config.coding;
  return (
    <section className="rounded-panel bg-settings-surface px-3 py-3 sm:px-4" aria-label={tx("coding.harnesses", "Coding agents")}>
      <div className="flex items-center justify-between gap-2 border-b border-border/45 pb-2">
        <div className="flex items-center gap-2 text-[13px] font-medium text-foreground">
          <Code2 className="h-4 w-4 text-emerald-600 dark:text-emerald-400" aria-hidden />
          {tx("coding.harnesses", "Coding agents")}
        </div>
        {coding ? (
          <StatusPill tone={coding.enabled ? "success" : "neutral"}>
            {coding.enabled ? tx("coding.on", "Enabled") : tx("coding.off", "Disabled")}
          </StatusPill>
        ) : null}
      </div>
      {error ? (
        <p role="alert" className="py-4 text-[13px] text-destructive">
          {error}
        </p>
      ) : !payload ? (
        <div className="flex h-24 items-center justify-center text-sm text-muted-foreground" role="status">
          <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden />
          {tx("loading", "Loading…")}
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-3 py-3 xl:grid-cols-2">
          {BACKENDS.map((backend) => {
            const info = payload.detection[backend.name];
            return (
              <article key={backend.name} data-backend={backend.name} className="rounded-xl border border-border/60 p-3">
                <div className="flex items-start justify-between gap-2">
                  <h3 className="text-[14px] font-medium text-foreground">{backend.title}</h3>
                  <StatusPill tone={info?.found ? "success" : "neutral"}>{stateLabel(info, tx)}</StatusPill>
                </div>
                <p className="mt-1 text-[12.5px] text-muted-foreground">{backend.blurb}</p>
                {info?.path ? <p className="mt-1 truncate font-mono text-[11.5px] text-muted-foreground">{info.path}</p> : null}
                <div className="mt-2 flex flex-wrap gap-1">
                  {backend.badges.map((badge) => (
                    <span key={badge} className="rounded-full bg-muted px-2 py-0.5 text-[11px] text-muted-foreground">
                      {badge}
                    </span>
                  ))}
                  {coding?.default_backend === backend.name ? (
                    <span className="rounded-full bg-primary/10 px-2 py-0.5 text-[11px] text-primary">
                      {tx("coding.defaultBackend", "Default backend")}
                    </span>
                  ) : null}
                </div>
              </article>
            );
          })}
        </div>
      )}
      {onConfigure ? (
        <div className="flex justify-end border-t border-border/45 pt-2">
          <Button type="button" size="sm" variant="outline" onClick={onConfigure}>
            {tx("configure", "Configure in Coworker settings")}
          </Button>
        </div>
      ) : null}
    </section>
  );
}

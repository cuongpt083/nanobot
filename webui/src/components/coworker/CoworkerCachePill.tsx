import { useEffect, useState } from "react";
import { Zap } from "lucide-react";
import { useTranslation } from "react-i18next";

import { CoworkerAutoOptimizeSection } from "@/components/coworker/CoworkerAutoOptimizeSection";
import { CoworkerKeepWarmSection } from "@/components/coworker/CoworkerKeepWarmSection";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import type { WebUIMutationTransport } from "@/lib/api";
import type { CoworkerStatus } from "@/lib/types";
import { cn } from "@/lib/utils";

interface CoworkerCachePillProps {
  client: WebUIMutationTransport;
  sessionKey: string;
  token: string;
  status: CoworkerStatus | null;
  onStatus: (status: CoworkerStatus) => void;
}

function formatCountdown(seconds: number): string {
  if (seconds <= 0) return "0s";
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  if (m <= 0) return `${s}s`;
  return `${m}m ${s < 10 ? "0" : ""}${s}s`;
}

export function CoworkerCachePill({
  client,
  sessionKey,
  status,
  onStatus,
}: CoworkerCachePillProps) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [now, setNow] = useState(() => Date.now() / 1000);

  useEffect(() => {
    const intervalMs = open ? 1000 : 15000;
    const timer = setInterval(() => {
      setNow(Date.now() / 1000);
    }, intervalMs);
    return () => clearInterval(timer);
  }, [open]);

  const caching = status?.caching;
  const keepalive = caching?.keepalive;

  if (!keepalive || !keepalive.known) {
    return null;
  }

  const remainingSeconds = keepalive.expires_at ? Math.max(0, keepalive.expires_at - now) : 0;
  const isWarm = Boolean(keepalive.expires_at && keepalive.expires_at > now);
  const isRunning = keepalive.run_active;

  let pillLabel = "";
  if (isRunning) {
    pillLabel = t("coworker.cache.running", { defaultValue: "Ấm (đang chạy)" });
  } else if (isWarm) {
    const prefix = keepalive.guaranteed ? "" : "~";
    const flame = keepalive.enabled ? " 🔥" : "";
    pillLabel = `${prefix}${formatCountdown(remainingSeconds)}${flame}`;
  } else {
    pillLabel = `❄️ ${t("coworker.cache.cold", { defaultValue: "Nguội" })}`;
  }

  const hitRate = caching.usage?.hit_rate;
  const hitRatePct = hitRate !== undefined && hitRate !== null ? Math.round(hitRate * 100) : null;

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <TooltipProvider>
        <Tooltip>
          <TooltipTrigger asChild>
            <PopoverTrigger asChild>
              <button
                type="button"
                aria-label={t("coworker.cache.title", { defaultValue: "Prompt Cache" })}
                data-header-pill=""
                className={cn(
                  "inline-flex h-7 items-center gap-1.5 rounded-full border px-2.5 text-[11px] font-medium transition-colors focus:outline-none focus:ring-1 focus:ring-ring",
                  isWarm || isRunning
                    ? "border-amber-300/70 bg-amber-50/80 text-amber-700 hover:bg-amber-100/80 dark:border-amber-700/60 dark:bg-amber-950/40 dark:text-amber-300 dark:hover:bg-amber-900/50"
                    : "border-sky-300/70 bg-sky-50/80 text-sky-700 hover:bg-sky-100/80 dark:border-sky-700/60 dark:bg-sky-950/40 dark:text-sky-300 dark:hover:bg-sky-900/50",
                )}
              >
                <Zap className={cn("h-3 w-3", isWarm || isRunning ? "text-amber-500" : "text-sky-500")} />
                <span>{pillLabel}</span>
              </button>
            </PopoverTrigger>
          </TooltipTrigger>
          <TooltipContent className="text-[11px]">
            {isWarm
              ? t("coworker.cache.tooltipWarm", { defaultValue: "Prompt cache is warm" })
              : t("coworker.cache.tooltipCold", { defaultValue: "Prompt cache is cold" })}
          </TooltipContent>
        </Tooltip>
      </TooltipProvider>

      <PopoverContent align="end" className="w-80 space-y-3 p-3.5 text-xs">
        <div className="space-y-1">
          <div className="flex items-center justify-between">
            <span className="font-semibold text-foreground">
              {t("coworker.cache.title", { defaultValue: "Prompt Cache" })}
            </span>
            <span className="text-[11px] text-muted-foreground">
              {keepalive.provider} · {keepalive.model}
            </span>
          </div>
          {hitRatePct !== null && (
            <div className="flex items-center justify-between text-[11px] text-muted-foreground pt-1">
              <span>{t("coworker.cache.hitRate", { defaultValue: "Hit rate" })}:</span>
              <span className="font-medium text-foreground">{hitRatePct}%</span>
            </div>
          )}
        </div>

        <CoworkerKeepWarmSection
          client={client}
          sessionKey={sessionKey}
          keepalive={keepalive}
          now={now}
          onStatus={onStatus}
        />

        <CoworkerAutoOptimizeSection
          client={client}
          sessionKey={sessionKey}
          caching={caching}
          onStatus={onStatus}
        />
      </PopoverContent>
    </Popover>
  );
}

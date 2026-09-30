import { useTranslation } from "react-i18next";

import { cn } from "@/lib/utils";
import type { CoworkerCacheUsage } from "@/lib/types";

export function formatTokens(value: number): string {
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
  if (value >= 10_000) return `${Math.round(value / 1000)}k`;
  if (value >= 1000) return `${(value / 1000).toFixed(1)}k`;
  return String(value);
}

export function formatPercent(rate: number | null | undefined): string {
  return rate === null || rate === undefined ? "–" : `${Math.round(rate * 100)}%`;
}

function tone(rate: number | null): string {
  if (rate === null) return "bg-muted-foreground/25";
  if (rate >= 0.6) return "bg-emerald-500";
  if (rate >= 0.25) return "bg-amber-500";
  return "bg-red-400";
}

/** Bars for the hit rate of the latest calls; an empty slot means the provider reported nothing. */
function HitRateBars({ rates }: { rates: Array<number | null> }) {
  return (
    <div className="flex h-6 items-end gap-0.5" role="img" aria-label="Cache hit rate of recent requests">
      {rates.map((rate, index) => (
        <span
          // The list is a sliding window, so position is the only stable identity.
          key={index}
          title={formatPercent(rate)}
          className={cn("w-1.5 rounded-sm", tone(rate))}
          style={{ height: `${rate === null ? 12 : Math.max(8, Math.round(rate * 100))}%` }}
        />
      ))}
    </div>
  );
}

/**
 * What the provider reported for this session: how much input came from cache versus was newly
 * written. Complements the optimizer figures above it, which describe what nanobot sent.
 */
export function CoworkerCacheUsageBlock({ usage }: { usage: CoworkerCacheUsage | undefined }) {
  const { t } = useTranslation();
  if (!usage) return null;

  if (usage.calls === 0) {
    return (
      <p className="mt-2.5 border-t border-border/40 pt-2 text-[11px] text-muted-foreground">
        {t("coworker.cache.none", { defaultValue: "No model requests yet in this session." })}
      </p>
    );
  }
  if (!usage.reported) {
    return (
      <p className="mt-2.5 border-t border-border/40 pt-2 text-[11px] text-muted-foreground">
        {t("coworker.cache.unreported", {
          defaultValue: "This provider does not report prompt-cache usage, so hit rate is unknown.",
        })}
      </p>
    );
  }

  return (
    <div className="mt-2.5 space-y-2 border-t border-border/40 pt-2">
      <div className="flex items-end justify-between gap-3">
        <div>
          <div className="text-[11px] text-muted-foreground">
            {t("coworker.cache.hitRate", { defaultValue: "Cache hit rate (session)" })}
          </div>
          <div className="text-lg font-semibold leading-tight text-foreground">
            {formatPercent(usage.hit_rate)}
          </div>
        </div>
        <HitRateBars rates={usage.recent_hit_rates} />
      </div>
      <div className="grid grid-cols-3 gap-2 text-[11.5px]">
        <div className="rounded-md bg-muted/40 p-2">
          <div className="text-muted-foreground">{t("coworker.cache.read", { defaultValue: "From cache" })}</div>
          <div className="mt-0.5 font-semibold text-foreground">{formatTokens(usage.cache_read_tokens)}</div>
        </div>
        <div className="rounded-md bg-muted/40 p-2">
          <div className="text-muted-foreground">{t("coworker.cache.write", { defaultValue: "Newly cached" })}</div>
          <div className="mt-0.5 font-semibold text-foreground">{formatTokens(usage.cache_write_tokens)}</div>
        </div>
        <div className="rounded-md bg-muted/40 p-2">
          <div className="text-muted-foreground">{t("coworker.cache.input", { defaultValue: "Input total" })}</div>
          <div className="mt-0.5 font-semibold text-foreground">{formatTokens(usage.input_tokens)}</div>
        </div>
      </div>
      {usage.last ? (
        <p className="text-[11px] text-muted-foreground">
          {t("coworker.cache.last", {
            defaultValue: "Last request: {{rate}} from cache ({{read}} of {{input}} tokens)",
            rate: formatPercent(usage.last.hit_rate),
            read: formatTokens(usage.last.cache_read_tokens ?? 0),
            input: formatTokens(usage.last.input_tokens),
          })}
        </p>
      ) : null}
    </div>
  );
}

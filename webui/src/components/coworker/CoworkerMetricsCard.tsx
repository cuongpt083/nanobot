import { Zap } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { formatPercent, formatTokens } from "@/components/coworker/CoworkerCacheUsage";
import { SettingsSectionTitle } from "@/components/settings/shared/SettingsControls";
import { usePageVisibility } from "@/hooks/usePageVisibility";
import { fetchCoworkerMetrics } from "@/lib/api";
import type { CoworkerMetricsDay, CoworkerMetricsHistory } from "@/lib/types";
import { useClient } from "@/providers/ClientProvider";

const REFRESH_INTERVAL_MS = 60_000;
const WINDOW_DAYS = 30;

function useCoworkerMetrics() {
  const { token } = useClient();
  const pageVisible = usePageVisibility();
  const [data, setData] = useState<CoworkerMetricsHistory | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!token) return;
    setLoading(true);
    try {
      const next = await fetchCoworkerMetrics(token);
      setData(next);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => {
    if (!pageVisible) return;
    void load();
    const timer = window.setInterval(() => void load(), REFRESH_INTERVAL_MS);
    const onFocus = () => void load();
    window.addEventListener("focus", onFocus);
    return () => {
      window.clearInterval(timer);
      window.removeEventListener("focus", onFocus);
    };
  }, [load, pageVisible]);

  return { data, loading, error };
}

/** 30 slots ending on the last day the server reported, so bars stay on a real timeline. */
function timelineSlots(days: CoworkerMetricsDay[]) {
  const byDate = new Map(days.map((day) => [day.date, day]));
  const anchor = days.length > 0 ? days[days.length - 1].date : new Date().toISOString().slice(0, 10);
  return Array.from({ length: WINDOW_DAYS }, (_, index) => {
    const date = new Date(`${anchor}T00:00:00Z`);
    date.setUTCDate(date.getUTCDate() - (WINDOW_DAYS - 1) + index);
    const key = date.toISOString().slice(0, 10);
    return { date: key, day: byDate.get(key) };
  });
}

function Kpi({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-md bg-muted/40 p-2" title={hint}>
      <div className="text-[11px] text-muted-foreground">{label}</div>
      <div className="mt-0.5 text-sm font-semibold tabular-nums text-foreground">{value}</div>
    </div>
  );
}

function MetricsBars({ days, timeZone }: { days: CoworkerMetricsDay[]; timeZone?: string }) {
  const { t } = useTranslation();
  const slots = timelineSlots(days);
  const peak = Math.max(1, ...slots.map((slot) => (slot.day?.cache_read_tokens ?? 0) + (slot.day?.cache_write_tokens ?? 0)));
  return (
    <div>
      <div className="grid h-20 grid-cols-[repeat(30,minmax(0,1fr))] gap-1" role="img" aria-label={t("coworker.metrics.trendLabel", { defaultValue: "Daily cache activity, last 30 days" })}>
        {slots.map((slot) => {
          const read = slot.day?.cache_read_tokens ?? 0;
          const write = slot.day?.cache_write_tokens ?? 0;
          const total = read + write;
          return (
            <span key={slot.date} className="flex h-full min-w-0 items-end rounded-sm">
              {total > 0 ? (
                <span className="flex w-full flex-col-reverse overflow-hidden rounded-t-sm" style={{ height: `${(total / peak) * 100}%` }}>
                  {read > 0 ? <span className="w-full shrink-0 bg-emerald-500/80" style={{ height: `${(read / total) * 100}%` }} /> : null}
                  {write > 0 ? <span className="w-full shrink-0 bg-sky-500/70" style={{ height: `${(write / total) * 100}%` }} /> : null}
                </span>
              ) : null}
            </span>
          );
        })}
      </div>
      <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-muted-foreground">
        <span className="flex items-center gap-1.5"><span className="size-2.5 rounded-sm bg-emerald-500/80" aria-hidden />{t("coworker.metrics.legendFromCache", { defaultValue: "From cache" })}</span>
        <span className="flex items-center gap-1.5"><span className="size-2.5 rounded-sm bg-sky-500/70" aria-hidden />{t("coworker.metrics.legendNewlyCached", { defaultValue: "Newly cached" })}</span>
        {timeZone ? <span className="ml-auto">{timeZone}</span> : null}
      </div>
    </div>
  );
}

/**
 * Read-only 30-day history for the three fork cache layers, mounted in the Coworker
 * settings Cache tab. Fork-local: no upstream component or locale file is touched.
 */
export function CoworkerMetricsCard({ timeZone }: { timeZone?: string }) {
  const { t } = useTranslation();
  const tx = (key: string, fallback: string) => t(`coworker.metrics.${key}`, { defaultValue: fallback });
  const { data, loading, error } = useCoworkerMetrics();

  const empty = !data || (data.total_turns_30d === 0 && data.total_pings_30d === 0);

  return (
    <div className="settings-stack">
      <SettingsSectionTitle>{tx("title", "Prompt cache & context (30 days)")}</SettingsSectionTitle>
      <div className="rounded-lg border border-border/60 bg-card p-3 shadow-xs">
        <div className="flex items-center gap-1.5 text-[12px] font-semibold text-foreground">
          <Zap className="h-3.5 w-3.5 text-amber-500" aria-hidden />
          <span>{tx("heading", "Caching, keep-warm & optimization")}</span>
        </div>

        {error && !data ? (
          <p className="mt-2 text-[12px] text-destructive" role="alert">{error}</p>
        ) : loading && !data ? (
          <p className="mt-2 text-[12px] text-muted-foreground" role="status">{tx("loading", "Loading…")}</p>
        ) : empty ? (
          <p className="mt-2 text-[12px] text-muted-foreground" role="status">
            {tx("empty", "No cache activity recorded in the last 30 days yet.")}
          </p>
        ) : (
          <div className="mt-2.5 space-y-3">
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
              <Kpi
                label={tx("cacheHitRate", "Cache hit rate")}
                value={formatPercent(data.cache_read_rate_30d)}
                hint={tx("cacheHitRateHint", "Share of cache-reporting input served from cache.")}
              />
              <Kpi label={tx("fromCache", "Tokens from cache")} value={formatTokens(data.cache_read_tokens_30d)} />
              <Kpi label={tx("newlyCached", "Tokens newly cached")} value={formatTokens(data.cache_write_tokens_30d)} />
              <Kpi
                label={tx("warmHits", "Keep-warm hits")}
                value={`${data.warm_hits_30d}/${data.total_pings_30d}`}
                hint={tx("warmHitsHint", "Successful keep-alive pings that refreshed a warm cache, out of all pings.")}
              />
            </div>

            <MetricsBars days={data.days} timeZone={timeZone} />

            <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
              <Kpi label={tx("turns", "Turns")} value={String(data.total_turns_30d)} />
              <Kpi label={tx("savedMessages", "Messages saved")} value={String(data.saved_messages_30d)} />
              <Kpi label={tx("trimmed", "Trimmed")} value={String(data.trimmed_messages_30d)} />
              <Kpi
                label={tx("pingFailures", "Ping failures")}
                value={String(data.ping_failures_30d)}
              />
            </div>

            {data.sources_30d.length > 0 ? (
              <dl className="grid grid-cols-1 gap-x-6 gap-y-1.5 border-t border-border/40 pt-2.5 text-xs sm:grid-cols-2" aria-label={tx("bySource", "Cache usage by source")}>
                {data.sources_30d.map((source) => (
                  <div key={source.source} className="flex min-w-0 items-center justify-between gap-2">
                    <dt className="min-w-0 truncate text-muted-foreground">
                      {t(`coworker.metrics.source.${source.source}`, {
                        defaultValue: source.source,
                      })}
                    </dt>
                    <dd className="shrink-0 tabular-nums">
                      {formatTokens(source.cache_read_tokens)} · {formatPercent(source.cache_read_rate)}
                    </dd>
                  </div>
                ))}
              </dl>
            ) : null}
          </div>
        )}
      </div>
    </div>
  );
}

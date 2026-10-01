import { useState } from "react";
import { AlertCircle, Flame, Info } from "lucide-react";
import { useTranslation } from "react-i18next";

import { SegmentedControl } from "@/components/ui/segmented-control";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { setCoworkerKeepalive, type WebUIMutationTransport } from "@/lib/api";
import type { CoworkerKeepaliveStatus, CoworkerKeepaliveSwitch, CoworkerStatus } from "@/lib/types";
import { cn } from "@/lib/utils";

interface CoworkerKeepWarmSectionProps {
  client: WebUIMutationTransport;
  sessionKey: string;
  keepalive: CoworkerKeepaliveStatus;
  now: number;
  onStatus: (status: CoworkerStatus) => void;
}

function formatMinutes(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  if (m <= 0) return `${s}s`;
  return `${m}m ${s < 10 ? "0" : ""}${s}s`;
}

export function CoworkerKeepWarmSection({
  client,
  sessionKey,
  keepalive,
  now,
  onStatus,
}: CoworkerKeepWarmSectionProps) {
  const { t } = useTranslation();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const apply = async (change: CoworkerKeepaliveSwitch) => {
    setBusy(true);
    setError(null);
    try {
      const next = await setCoworkerKeepalive(client, sessionKey, change);
      onStatus(next);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const modeValue: "global" | "on" | "off" =
    keepalive.source === "global" ? "global" : keepalive.enabled ? "on" : "off";

  const remainingSeconds = keepalive.expires_at ? Math.max(0, keepalive.expires_at - now) : 0;
  const isExpired = remainingSeconds <= 0;
  const isWindowPast =
    keepalive.real_turn_at !== null && now - keepalive.real_turn_at > keepalive.window_min * 60;

  return (
    <div className="space-y-3 pt-2">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1.5 text-[12px] font-semibold text-foreground">
          <Flame className="h-3.5 w-3.5 text-amber-500" />
          <span>{t("coworker.keepWarm.title", { defaultValue: "Keep-warm prompt cache" })}</span>
        </div>
        <TooltipProvider>
          <Tooltip>
            <TooltipTrigger asChild>
              <button type="button" className="text-muted-foreground hover:text-foreground">
                <Info className="h-3.5 w-3.5" />
              </button>
            </TooltipTrigger>
            <TooltipContent className="max-w-xs text-[11px]">
              {t("coworker.keepWarm.tooltip", {
                defaultValue:
                  "Re-reads the prompt cache shortly before it expires to refresh the TTL at cache-read price (~0.1× write).",
              })}
            </TooltipContent>
          </Tooltip>
        </TooltipProvider>
      </div>

      {error && <div className="text-[11px] text-destructive">{error}</div>}

      <div className={cn("space-y-1.5", busy && "pointer-events-none opacity-60")}>
        <SegmentedControl<"global" | "on" | "off">
          ariaLabel={t("coworker.keepWarm.modeLabel", { defaultValue: "Keep-warm mode" })}
          value={modeValue}
          options={[
            {
              value: "global",
              label: t("coworker.keepWarm.modeGlobal", { defaultValue: "Theo cài đặt chung" }),
            },
            {
              value: "on",
              label: t("coworker.keepWarm.modeOn", { defaultValue: "Bật" }),
            },
            {
              value: "off",
              label: t("coworker.keepWarm.modeOff", { defaultValue: "Tắt" }),
            },
          ]}
          onChange={(next) => {
            if (next === "global") void apply({ enabled: null });
            else if (next === "on") void apply({ enabled: true });
            else void apply({ enabled: false });
          }}
        />
      </div>

      {keepalive.ttl1h_supported && (
        <div className="space-y-1.5">
          <div className="text-[11px] font-medium text-muted-foreground">
            {t("coworker.keepWarm.strategy", { defaultValue: "Chiến lược" })}
          </div>
          <Select
            value={keepalive.strategy}
            disabled={busy || !keepalive.enabled}
            onValueChange={(val) => void apply({ strategy: val as "ping" | "ttl1h" })}
          >
            <SelectTrigger className="h-7 text-[12px]">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="ping" className="text-[12px]">
                {t("coworker.keepWarm.strategyPing", { defaultValue: "Ping định kỳ (~5 phút)" })}
              </SelectItem>
              <SelectItem value="ttl1h" className="text-[12px]">
                {t("coworker.keepWarm.strategyTtl1h", { defaultValue: "Giữ 1 giờ (ttl1h)" })}
              </SelectItem>
            </SelectContent>
          </Select>
        </div>
      )}

      <div className="space-y-1.5">
        <div className="text-[11px] font-medium text-muted-foreground">
          {t("coworker.keepWarm.window", { defaultValue: "Cửa sổ giữ ấm" })}
        </div>
        <Select
          value={String(keepalive.window_min)}
          disabled={busy || !keepalive.enabled}
          onValueChange={(val) => void apply({ window_min: Number(val) })}
        >
          <SelectTrigger className="h-7 text-[12px]">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="15" className="text-[12px]">15 phút</SelectItem>
            <SelectItem value="30" className="text-[12px]">30 phút</SelectItem>
            <SelectItem value="60" className="text-[12px]">60 phút</SelectItem>
            <SelectItem value="120" className="text-[12px]">120 phút</SelectItem>
          </SelectContent>
        </Select>
      </div>

      <div className="rounded border bg-muted/30 p-2 text-[11px] space-y-1">
        {keepalive.parked ? (
          <div className="flex items-center gap-1.5 text-destructive font-medium">
            <AlertCircle className="h-3.5 w-3.5 shrink-0" />
            <span>
              {t("coworker.keepWarm.parked", {
                defaultValue: "Tạm dừng ping sau lỗi",
              })}
              : {keepalive.last_error}
            </span>
          </div>
        ) : keepalive.can_ping ? (
          <div className="text-amber-600 dark:text-amber-400 font-medium">
            ⏳ Còn {formatMinutes(remainingSeconds)} · {keepalive.pings}/{keepalive.ping_cap} ping
          </div>
        ) : keepalive.pings >= keepalive.ping_cap && keepalive.enabled ? (
          <div className="text-muted-foreground">
            ⏹ Đã đủ {keepalive.ping_cap} ping, để nguội
          </div>
        ) : isWindowPast && keepalive.enabled ? (
          <div className="text-muted-foreground">
            ⏹ Hết cửa sổ giữ ấm ({keepalive.window_min}m)
          </div>
        ) : keepalive.effective_strategy === "ttl1h" ? (
          <div className="text-muted-foreground">
            {keepalive.ttl1h_armed
              ? "ttl1h: Đang giữ cache 1 giờ"
              : "ttl1h: Sẽ áp dụng từ lần gửi kế"}
          </div>
        ) : (
          <div className="text-muted-foreground">
            {isExpired ? "❄️ Cache đang nguội" : `⏳ Hết hạn sau ${formatMinutes(remainingSeconds)}`}
          </div>
        )}

        <div className="flex items-center justify-between text-[10px] text-muted-foreground pt-1 border-t">
          <span>Ước tính: ~{keepalive.est_tokens_per_ping} tok/ping</span>
          <span>Đã dùng: {keepalive.spent.pings || 0} ping</span>
        </div>
      </div>
    </div>
  );
}

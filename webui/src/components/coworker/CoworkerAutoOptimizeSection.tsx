import { useState } from "react";
import { Sparkles } from "lucide-react";
import { useTranslation } from "react-i18next";

import { ToggleButton } from "@/components/settings/ToggleButton";
import { setCoworkerContext, type WebUIMutationTransport } from "@/lib/api";
import type { CoworkerCachingStatus, CoworkerStatus } from "@/lib/types";

interface CoworkerAutoOptimizeSectionProps {
  client: WebUIMutationTransport;
  sessionKey: string;
  caching: CoworkerCachingStatus;
  onStatus: (status: CoworkerStatus) => void;
}

export function CoworkerAutoOptimizeSection({
  client,
  sessionKey,
  caching,
  onStatus,
}: CoworkerAutoOptimizeSectionProps) {
  const { t } = useTranslation();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const apply = async (optimize: boolean) => {
    setBusy(true);
    setError(null);
    try {
      const next = await setCoworkerContext(client, sessionKey, { optimize });
      onStatus(next);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-2 pt-2 border-t">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1.5 text-[12px] font-semibold text-foreground">
          <Sparkles className="h-3.5 w-3.5 text-blue-500" />
          <span>{t("coworker.autoOptimize.title", { defaultValue: "Auto-optimize context" })}</span>
        </div>
        <ToggleButton
          checked={caching.enabled}
          disabled={busy}
          label={t("coworker.autoOptimize.toggle", { defaultValue: "Auto-optimize context" })}
          onChange={(val) => void apply(val)}
        />
      </div>
      {error && <div className="text-[11px] text-destructive">{error}</div>}
      <p className="text-[11px] text-muted-foreground">
        {t("coworker.autoOptimize.description", {
          defaultValue:
            "Trims redundant history and drops dead tool calls while keeping prompt cache stable.",
        })}
      </p>
    </div>
  );
}

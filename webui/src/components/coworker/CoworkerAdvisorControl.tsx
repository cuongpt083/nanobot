import { useEffect, useMemo, useState } from "react";
import { Brain } from "lucide-react";
import { useTranslation } from "react-i18next";

import { CoworkerAdvisorExchanges } from "@/components/coworker/CoworkerAdvisorExchanges";
import { ToggleButton } from "@/components/settings/ToggleButton";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { SegmentedControl } from "@/components/ui/segmented-control";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import {
  fetchCoworkerSettings,
  setCoworkerAdvisor,
  type WebUIMutationTransport,
} from "@/lib/api";
import type {
  CoworkerAdvisorMode,
  CoworkerAdvisorSwitch,
  CoworkerStatus,
} from "@/lib/types";
import { cn } from "@/lib/utils";

interface CoworkerAdvisorControlProps {
  client: WebUIMutationTransport;
  sessionKey: string;
  token: string;
  status: CoworkerStatus | null;
  onStatus: (status: CoworkerStatus) => void;
}

/** Header switch that turns the advisor on for this conversation, coding or not. */
export function CoworkerAdvisorControl({
  client,
  sessionKey,
  token,
  status,
  onStatus,
}: CoworkerAdvisorControlProps) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [presets, setPresets] = useState<string[]>([]);
  const [chosenPreset, setChosenPreset] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const advisor = status?.advisor;
  const enabled = advisor?.enabled ?? false;
  const mode: CoworkerAdvisorMode = advisor?.mode ?? "coding";

  useEffect(() => {
    if (!open || presets.length > 0) return;
    let cancelled = false;
    fetchCoworkerSettings(token)
      .then((payload) => {
        if (!cancelled) setPresets(payload.presets ?? []);
      })
      .catch(() => {
        // The switch still works with the session's or the global default preset.
      });
    return () => {
      cancelled = true;
    };
  }, [open, presets.length, token]);

  const preset = useMemo(() => {
    if (chosenPreset) return chosenPreset;
    if (advisor?.preset) return advisor.preset;
    if (advisor?.default_preset) return advisor.default_preset;
    return presets.find((name) => name !== "default") ?? presets[0] ?? "";
  }, [advisor?.default_preset, advisor?.preset, chosenPreset, presets]);
  const presetOptions = useMemo(
    () => Array.from(new Set([preset, ...presets].filter(Boolean))),
    [preset, presets],
  );

  const apply = async (change: CoworkerAdvisorSwitch) => {
    setBusy(true);
    setError(null);
    try {
      onStatus(await setCoworkerAdvisor(client, sessionKey, change));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(false);
    }
  };

  const label = t("coworker.advisorControl.title", { defaultValue: "Advisor" });

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <TooltipProvider>
        <Tooltip>
          <TooltipTrigger asChild>
            <PopoverTrigger asChild>
              <button
                type="button"
                aria-label={label}
                aria-pressed={enabled}
                className={cn(
                  "host-no-drag relative inline-flex h-8 items-center gap-1.5 rounded-full px-2.5 text-[12px] font-medium transition-colors",
                  enabled
                    ? "bg-violet-500/12 text-violet-700 hover:bg-violet-500/18 dark:text-violet-300"
                    : "text-muted-foreground/85 hover:bg-accent/40 hover:text-foreground",
                )}
              >
                <Brain className="h-4 w-4" aria-hidden />
                <span className="hidden sm:inline">{label}</span>
                {enabled ? (
                  <span className="hidden text-[10.5px] font-normal opacity-80 md:inline">
                    {mode === "brainstorm"
                      ? t("coworker.advisorControl.modeBrainstorm", { defaultValue: "Brainstorm" })
                      : t("coworker.advisorControl.modeCoding", { defaultValue: "Coding" })}
                  </span>
                ) : null}
              </button>
            </PopoverTrigger>
          </TooltipTrigger>
          <TooltipContent side="bottom" align="end">
            {enabled
              ? t("coworker.advisorControl.tooltipOn", { defaultValue: "Advisor is on for this chat" })
              : t("coworker.advisorControl.tooltipOff", { defaultValue: "Turn on a second-opinion model for this chat" })}
          </TooltipContent>
        </Tooltip>
      </TooltipProvider>

      <PopoverContent align="end" sideOffset={8} className="w-[min(22rem,calc(100vw-1.5rem))] space-y-3 p-3.5 text-xs">
        <div className="flex items-center justify-between gap-3">
          <div>
            <div className="text-[13px] font-semibold text-foreground">{label}</div>
            <p className="mt-0.5 text-[11px] text-muted-foreground">
              {t("coworker.advisorControl.description", {
                defaultValue: "A stronger model the agent consults for a second opinion. Works for any topic, not just code.",
              })}
            </p>
          </div>
          <ToggleButton
            checked={enabled}
            disabled={busy || (!enabled && !preset)}
            label={t("coworker.advisorControl.toggle", { defaultValue: "Advisor for this chat" })}
            onChange={(next) => void apply(next ? { enabled: true, preset } : { enabled: false })}
          />
        </div>

        <div className="space-y-1.5">
          <div className="text-[11px] font-medium text-muted-foreground">
            {t("coworker.advisorControl.mode", { defaultValue: "Use it for" })}
          </div>
          <SegmentedControl<CoworkerAdvisorMode>
            ariaLabel={t("coworker.advisorControl.mode", { defaultValue: "Use it for" })}
            value={mode}
            options={[
              { value: "brainstorm", label: t("coworker.advisorControl.modeBrainstorm", { defaultValue: "Brainstorm" }) },
              { value: "coding", label: t("coworker.advisorControl.modeCoding", { defaultValue: "Coding" }) },
            ]}
            onChange={(next) => void apply({ mode: next })}
          />
          <p className="text-[11px] text-muted-foreground">
            {mode === "brainstorm"
              ? t("coworker.advisorControl.hintBrainstorm", {
                  defaultValue: "Discussion and decisions: the agent asks for a second opinion before it recommends something.",
                })
              : t("coworker.advisorControl.hintCoding", {
                  defaultValue: "Engineering work: the agent reads the code first, consults before it writes, and again before it finishes.",
                })}
          </p>
        </div>

        <div className="space-y-1.5">
          <div className="text-[11px] font-medium text-muted-foreground">
            {t("coworker.advisorControl.model", { defaultValue: "Advisor model" })}
          </div>
          <Select
            value={preset}
            disabled={busy || presetOptions.length === 0}
            onValueChange={(next) => {
              setChosenPreset(next);
              if (enabled) void apply({ preset: next });
            }}
          >
            <SelectTrigger className="h-8 w-full" aria-label={t("coworker.advisorControl.model", { defaultValue: "Advisor model" })}>
              <SelectValue placeholder={t("coworker.advisorControl.choosePreset", { defaultValue: "Choose a model preset" })} />
            </SelectTrigger>
            <SelectContent>
              {presetOptions.map((name) => (
                <SelectItem key={name} value={name}>{name}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        {error ? (
          <p role="alert" className="rounded-md bg-red-500/10 px-2 py-1.5 text-[11px] text-red-600 dark:text-red-400">
            {error}
          </p>
        ) : null}

        {enabled ? (
          <div className="space-y-1.5 border-t border-border/40 pt-2.5">
            <div className="flex items-center justify-between text-[11px] text-muted-foreground">
              <span className="font-medium">
                {t("coworker.advisorExchanges.title", { defaultValue: "Advisor Q&A" })}
              </span>
              <span>
                {t("coworker.participants.uses", {
                  used: advisor?.uses ?? 0,
                  max: advisor?.max_uses ?? 0,
                  defaultValue: "{{used}}/{{max}} consults",
                })}
              </span>
            </div>
            <div className="max-h-56 overflow-y-auto overscroll-contain">
              <CoworkerAdvisorExchanges exchanges={advisor?.history} />
            </div>
          </div>
        ) : null}
      </PopoverContent>
    </Popover>
  );
}

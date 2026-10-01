import { useState } from "react";
import { Check, User, Users } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { setCoworkerPersona, type WebUIMutationTransport } from "@/lib/api";
import type { CoworkerPersonaInfo, CoworkerStatus } from "@/lib/types";
import { cn } from "@/lib/utils";

interface CoworkerPersonaControlProps {
  client: WebUIMutationTransport;
  sessionKey: string;
  token: string;
  status: CoworkerStatus | null;
  onStatus: (status: CoworkerStatus) => void;
}

export function CoworkerPersonaControl({
  client,
  sessionKey,
  status,
  onStatus,
}: CoworkerPersonaControlProps) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const persona = status?.persona;
  const personas = status?.personas ?? [];

  if (personas.length === 0 && !persona) {
    return null;
  }

  const selectPersona = async (id: string | null) => {
    setBusy(true);
    setError(null);
    try {
      const updated = await setCoworkerPersona(client, sessionKey, id);
      onStatus(updated);
      setOpen(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const label = persona
    ? `${persona.emoji ? `${persona.emoji} ` : ""}${persona.name || persona.id}`
    : t("coworker.persona.default", { defaultValue: "Persona" });

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <TooltipProvider>
        <Tooltip>
          <TooltipTrigger asChild>
            <PopoverTrigger asChild>
              <button
                type="button"
                data-testid="persona-control-btn"
                data-header-pill=""
                aria-label={label}
                aria-pressed={Boolean(persona)}
                className={cn(
                  "inline-flex h-8 items-center gap-1.5 rounded-full border px-2.5 text-xs font-medium transition-colors",
                  persona
                    ? "border-primary/40 bg-primary/10 text-primary hover:bg-primary/15"
                    : "border-border/70 bg-background/80 text-muted-foreground hover:bg-accent hover:text-foreground",
                )}
              >
                {persona ? (
                  <>
                    {persona.emoji ? <span>{persona.emoji}</span> : <Users className="h-3.5 w-3.5" />}
                    <span className="max-w-[120px] truncate">{persona.name || persona.id}</span>
                  </>
                ) : (
                  <>
                    <User className="h-3.5 w-3.5" />
                    <span>{t("coworker.persona.title", { defaultValue: "Persona" })}</span>
                  </>
                )}
              </button>
            </PopoverTrigger>
          </TooltipTrigger>
          <TooltipContent side="bottom">
            {persona
              ? t("coworker.persona.activeTooltip", {
                  name: persona.name || persona.id,
                  defaultValue: "Current persona: {{name}}",
                })
              : t("coworker.persona.tooltip", {
                  defaultValue: "Choose session persona",
                })}
          </TooltipContent>
        </Tooltip>
      </TooltipProvider>

      <PopoverContent align="end" className="w-80 space-y-3 p-3">
        <div className="flex items-center justify-between border-b border-border/40 pb-2">
          <div className="flex items-center gap-1.5 font-medium text-xs">
            <Users className="h-3.5 w-3.5 text-primary" />
            <span>{t("coworker.persona.heading", { defaultValue: "Session Persona" })}</span>
          </div>
          {persona ? (
            <button
              type="button"
              data-testid="persona-clear-btn"
              disabled={busy}
              onClick={() => void selectPersona(null)}
              className="text-[11px] text-muted-foreground hover:text-foreground hover:underline cursor-pointer"
            >
              {t("coworker.persona.reset", { defaultValue: "Reset to default" })}
            </button>
          ) : null}
        </div>

        {status?.caching?.is_warm ? (
          <div
            data-testid="persona-cache-warning"
            className="rounded-md border border-amber-500/20 bg-amber-500/10 p-2 text-[11px] text-amber-700 dark:text-amber-400"
          >
            {t("coworker.persona.cacheWarning", {
              defaultValue: "Thay đổi persona sẽ làm vỡ cache ấm ở lần gửi kế tiếp.",
            })}
          </div>
        ) : null}

        {error ? (
          <p role="alert" className="rounded-md bg-red-500/10 px-2 py-1.5 text-[11px] text-red-600 dark:text-red-400">
            {error}
          </p>
        ) : null}

        <div className="space-y-1 max-h-64 overflow-y-auto">
          {/* Default option */}
          <button
            type="button"
            data-testid="persona-option-default"
            disabled={busy}
            onClick={() => void selectPersona(null)}
            className={cn(
              "flex w-full items-center justify-between rounded-md p-2 text-left text-xs transition-colors hover:bg-accent",
              !persona && "bg-accent/60 font-medium",
            )}
          >
            <div className="flex items-center gap-2">
              <span className="grid h-5 w-5 place-items-center rounded bg-muted text-xs">
                <User className="h-3 w-3" />
              </span>
              <div>
                <p className="leading-tight">{t("coworker.persona.defaultCoordinator", { defaultValue: "Default Coordinator" })}</p>
                <p className="text-[10px] text-muted-foreground">{t("coworker.persona.defaultDesc", { defaultValue: "No persona override" })}</p>
              </div>
            </div>
            {!persona && <Check className="h-3.5 w-3.5 text-primary" />}
          </button>

          {/* Configured teammates */}
          {personas.map((p: CoworkerPersonaInfo) => {
            const active = persona?.id === p.id;
            return (
              <button
                key={p.id}
                type="button"
                data-testid={`persona-option-${p.id}`}
                disabled={busy}
                onClick={() => void selectPersona(p.id)}
                className={cn(
                  "flex w-full items-center justify-between rounded-md p-2 text-left text-xs transition-colors hover:bg-accent",
                  active && "bg-accent/60 font-medium",
                )}
              >
                <div className="flex items-center gap-2 min-w-0 flex-1">
                  <span className="grid h-5 w-5 place-items-center rounded bg-muted text-xs shrink-0">
                    {p.emoji || "👤"}
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-1.5">
                      <span className="truncate leading-tight">{p.name || p.id}</span>
                      {p.preset && (
                        <span className="rounded bg-muted px-1 py-0.2 text-[9px] text-muted-foreground font-mono">
                          {p.preset}
                        </span>
                      )}
                    </div>
                    {p.bio && <p className="truncate text-[10px] text-muted-foreground">{p.bio}</p>}
                  </div>
                </div>
                {active && <Check className="h-3.5 w-3.5 text-primary shrink-0 ml-1.5" />}
              </button>
            );
          })}
        </div>
      </PopoverContent>
    </Popover>
  );
}

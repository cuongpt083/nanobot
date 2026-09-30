import { useState } from "react";
import {
  Brain,
  Code2,
  Flame,
  Layers,
  RefreshCcw,
  Snowflake,
  Sparkles,
  Users,
  Zap,
} from "lucide-react";

import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { useCoworkerStatus } from "@/hooks/useCoworkerStatus";
import { cn } from "@/lib/utils";

interface CoworkerInspectorPopoverProps {
  sessionKey: string;
  token: string;
}

export function CoworkerInspectorPopover({
  sessionKey,
  token,
}: CoworkerInspectorPopoverProps) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const { status, loading, liveRemainingSeconds } = useCoworkerStatus(
    open,
    token,
    sessionKey,
  );

  const isWarm = status?.caching?.is_warm ?? false;

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <TooltipProvider>
        <Tooltip>
          <TooltipTrigger asChild>
            <PopoverTrigger asChild>
              <Button
                variant="ghost"
                size="icon"
                aria-label={t("coworker.inspector.title", { defaultValue: "Coworker Inspector" })}
                className={cn(
                  "host-no-drag relative h-8 w-8 rounded-full text-muted-foreground/85 hover:bg-accent/40 hover:text-foreground",
                  isWarm && "text-amber-600 dark:text-amber-400",
                )}
              >
                <Layers className="h-4 w-4" />
                {isWarm ? (
                  <span className="absolute right-1 top-1 flex h-2 w-2">
                    <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75" />
                    <span className="relative inline-flex h-2 w-2 rounded-full bg-emerald-500" />
                  </span>
                ) : null}
              </Button>
            </PopoverTrigger>
          </TooltipTrigger>
          <TooltipContent side="bottom" align="end">
            {t("coworker.inspector.tooltip", {
              defaultValue: "Coworker Inspector (Cache, Advisor, Room)",
            })}
          </TooltipContent>
        </Tooltip>
      </TooltipProvider>

      <PopoverContent
        align="end"
        sideOffset={8}
        className="w-[min(26rem,calc(100vw-1.5rem))] overflow-hidden p-0 shadow-lg"
      >
        <div className="flex max-h-[min(var(--radix-popover-content-available-height),36rem)] flex-col">
          {/* Header */}
          <div className="border-b border-border/45 bg-muted/30 px-4 py-3">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <span className="flex h-6 w-6 items-center justify-center rounded-md bg-primary/10 text-primary">
                  <Zap className="h-3.5 w-3.5" />
                </span>
                <span className="text-[13px] font-semibold text-foreground">
                  {t("coworker.inspector.heading", { defaultValue: "AICoworker Inspector" })}
                </span>
              </div>
              {loading ? (
                <RefreshCcw className="h-3.5 w-3.5 animate-spin text-muted-foreground" />
              ) : null}
            </div>
            <p className="mt-0.5 text-[11px] text-muted-foreground">
              {t("coworker.inspector.subheading", {
                defaultValue: "Real-time context caching, advisor reviews, room & coding tasks",
              })}
            </p>
          </div>

          {/* Body */}
          <div className="min-h-0 flex-1 space-y-3.5 overflow-y-auto overscroll-contain p-3.5 text-xs">
            {/* 1. Context Cache & Optimizer */}
            <div className="rounded-lg border border-border/60 bg-card p-3 shadow-xs">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-1.5 font-medium text-foreground">
                  <Zap className="h-3.5 w-3.5 text-amber-500" />
                  <span>{t("coworker.inspector.cacheTitle", { defaultValue: "Prompt Cache & Trim" })}</span>
                </div>
                {isWarm ? (
                  <span className="inline-flex items-center gap-1 rounded-full bg-emerald-500/10 px-2 py-0.5 text-[11px] font-medium text-emerald-600 dark:text-emerald-400">
                    <Flame className="h-3 w-3 text-emerald-500" />
                    {t("coworker.inspector.warm", { defaultValue: "Warm" })} ({liveRemainingSeconds}s)
                  </span>
                ) : (
                  <span className="inline-flex items-center gap-1 rounded-full bg-muted px-2 py-0.5 text-[11px] font-medium text-muted-foreground">
                    <Snowflake className="h-3 w-3 text-sky-400" />
                    {t("coworker.inspector.cold", { defaultValue: "Cold (Idle)" })}
                  </span>
                )}
              </div>

              <div className="mt-2.5 grid grid-cols-2 gap-2 text-[11.5px]">
                <div className="rounded-md bg-muted/40 p-2">
                  <div className="text-muted-foreground">{t("coworker.inspector.ttl", { defaultValue: "Cache TTL" })}</div>
                  <div className="mt-0.5 font-semibold text-foreground">
                    {status?.caching ? `${status.caching.ttl_seconds}s` : "300s"}
                  </div>
                </div>
                <div className="rounded-md bg-muted/40 p-2">
                  <div className="text-muted-foreground">{t("coworker.inspector.trimmed", { defaultValue: "Trimmed Turns" })}</div>
                  <div className="mt-0.5 font-semibold text-foreground">
                    {status?.caching?.trimmed_messages ?? 0}
                  </div>
                </div>
                <div className="rounded-md bg-muted/40 p-2">
                  <div className="text-muted-foreground">{t("coworker.inspector.wasted", { defaultValue: "Dead Weight Dropped" })}</div>
                  <div className="mt-0.5 font-semibold text-foreground">
                    {status?.caching?.wasted_tools ?? 0} tools
                  </div>
                </div>
                <div className="rounded-md bg-muted/40 p-2">
                  <div className="text-muted-foreground">{t("coworker.inspector.prefix", { defaultValue: "Prefix Freeze" })}</div>
                  <div className="mt-0.5 font-semibold text-foreground">
                    {status?.caching?.system_frozen ? "Active (Warm)" : "Dynamic"}
                  </div>
                </div>
              </div>
            </div>

            {/* 2. Senior Advisor */}
            <div className="rounded-lg border border-border/60 bg-card p-3 shadow-xs">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-1.5 font-medium text-foreground">
                  <Brain className="h-3.5 w-3.5 text-violet-500" />
                  <span>{t("coworker.inspector.advisorTitle", { defaultValue: "Senior Advisor" })}</span>
                </div>
                {status?.advisor?.enabled ? (
                  <span className="inline-flex items-center gap-1 rounded-full bg-violet-500/10 px-2 py-0.5 text-[11px] font-medium text-violet-600 dark:text-violet-400">
                    <Sparkles className="h-3 w-3" />
                    {status.advisor.preset || "Default"}
                  </span>
                ) : (
                  <span className="rounded-full bg-muted px-2 py-0.5 text-[11px] text-muted-foreground">
                    {t("coworker.inspector.disabled", { defaultValue: "Disabled" })}
                  </span>
                )}
              </div>

              {status?.advisor?.enabled ? (
                <div className="mt-2.5 space-y-1.5 text-[11.5px]">
                  <div className="flex items-center justify-between text-muted-foreground">
                    <span>{t("coworker.inspector.consultBudget", { defaultValue: "Consult Budget" })}:</span>
                    <span className="font-semibold text-foreground">
                      {status.advisor.uses} / {status.advisor.max_uses} used
                    </span>
                  </div>
                  <div className="flex items-center justify-between text-muted-foreground">
                    <span>{t("coworker.inspector.circuitBreaker", { defaultValue: "Circuit Breaker" })}:</span>
                    <span className="font-semibold text-foreground">
                      {status.advisor.breaker_open_seconds > 0
                        ? `Paused (${status.advisor.breaker_open_seconds}s)`
                        : "Operational"}
                    </span>
                  </div>
                </div>
              ) : null}
            </div>

            {/* 3. Room & Teammates */}
            <div className="rounded-lg border border-border/60 bg-card p-3 shadow-xs">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-1.5 font-medium text-foreground">
                  <Users className="h-3.5 w-3.5 text-sky-500" />
                  <span>{t("coworker.inspector.roomTitle", { defaultValue: "Room & Teammates" })}</span>
                </div>
                {status?.room?.armed ? (
                  <span className="rounded-full bg-sky-500/10 px-2 py-0.5 text-[11px] font-medium text-sky-600 dark:text-sky-400">
                    {t("coworker.inspector.armed", { defaultValue: "Armed" })}
                  </span>
                ) : (
                  <span className="rounded-full bg-muted px-2 py-0.5 text-[11px] text-muted-foreground">
                    {t("coworker.inspector.idle", { defaultValue: "Idle" })}
                  </span>
                )}
              </div>

              <div className="mt-2.5">
                <div className="text-[11px] text-muted-foreground">
                  {t("coworker.inspector.availableAgents", { defaultValue: "Available Agents" })}:
                </div>
                <div className="mt-1 flex flex-wrap gap-1">
                  {status?.room?.agents && status.room.agents.length > 0 ? (
                    status.room.agents.map((agent) => (
                      <span
                        key={agent}
                        className="rounded-md border border-border/60 bg-muted/40 px-1.5 py-0.5 text-[11px] font-mono text-foreground"
                      >
                        @{agent}
                      </span>
                    ))
                  ) : (
                    <span className="text-[11px] text-muted-foreground">None configured</span>
                  )}
                </div>

                {status?.room?.state_entries && status.room.state_entries.length > 0 ? (
                  <div className="mt-2.5 border-t border-border/40 pt-2">
                    <div className="text-[11px] text-muted-foreground">Shared Room State:</div>
                    <div className="mt-1 space-y-1">
                      {status.room.state_entries.slice(0, 4).map((entry) => (
                        <div key={entry.key} className="truncate text-[11px] font-mono">
                          <span className="text-primary font-semibold">{entry.key}:</span>{" "}
                          <span className="text-muted-foreground">{entry.preview}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                ) : null}
              </div>
            </div>

            {/* 4. Coding Agent */}
            <div className="rounded-lg border border-border/60 bg-card p-3 shadow-xs">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-1.5 font-medium text-foreground">
                  <Code2 className="h-3.5 w-3.5 text-emerald-500" />
                  <span>{t("coworker.inspector.codingTitle", { defaultValue: "Coding Tasks" })}</span>
                </div>
                <span className="rounded-full bg-emerald-500/10 px-2 py-0.5 text-[11px] font-medium text-emerald-600 dark:text-emerald-400">
                  {status?.coding?.tasks?.length ?? 0} tasks
                </span>
              </div>

              {status?.coding?.tasks && status.coding.tasks.length > 0 ? (
                <div className="mt-2.5 space-y-2">
                  {status.coding.tasks.slice(0, 3).map((task) => (
                    <div
                      key={task.id}
                      className="rounded-md border border-border/50 bg-muted/20 p-2 text-[11px]"
                    >
                      <div className="flex items-center justify-between gap-1">
                        <span className="font-mono font-medium text-foreground">{task.id}</span>
                        <span
                          className={cn(
                            "rounded-full px-1.5 py-0.2 text-[10px] uppercase font-semibold",
                            task.status === "succeeded"
                              ? "bg-emerald-500/15 text-emerald-600 dark:text-emerald-400"
                              : task.status === "running"
                                ? "bg-amber-500/15 text-amber-600 dark:text-amber-400"
                                : "bg-muted text-muted-foreground",
                          )}
                        >
                          {task.status}
                        </span>
                      </div>
                      <div className="mt-1 line-clamp-1 text-muted-foreground">{task.brief}</div>
                      {task.diffstat ? (
                        <div className="mt-0.5 font-mono text-[10.5px] text-muted-foreground">
                          {task.diffstat}
                        </div>
                      ) : null}
                    </div>
                  ))}
                </div>
              ) : (
                <p className="mt-2 text-[11px] text-muted-foreground">No coding tasks yet.</p>
              )}
            </div>
          </div>
        </div>
      </PopoverContent>
    </Popover>
  );
}

import { useEffect, useState } from "react";
import {
  Layers,
  RefreshCw,
  Cpu,
  FileText,
  Wrench,
  MessageSquare,
  ChevronDown,
  ChevronRight,
  Info,
  CheckSquare,
  Square,
} from "lucide-react";

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
import { cn } from "@/lib/utils";
import {
  fetchContextInspect,
  updateContextExclusions,
  type ContextSnapshot,
  type ContextRules,
} from "@/lib/contextInspector";
import type { WebUIMutationTransport } from "@/lib/api";

interface ContextInspectorPopoverProps {
  sessionKey: string;
  token: string;
  client: WebUIMutationTransport;
}

function fmtTokens(n: number): string {
  if (!Number.isFinite(n)) return "?";
  if (n < 1000) return String(n);
  if (n < 1_000_000) return `${(n / 1000).toFixed(1)}k`;
  return `${(n / 1_000_000).toFixed(1)}M`;
}

export function ContextInspectorPopover({
  sessionKey,
  token,
  client,
}: ContextInspectorPopoverProps) {
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [data, setData] = useState<ContextSnapshot | null>(null);

  const [rules, setRules] = useState<ContextRules>({
    system_sections: [],
    tools: [],
    message_idx: [],
    wasted_ids: [],
  });

  const [expandedSections, setExpandedSections] = useState({
    system: true,
    tools: false,
    messages: false,
  });

  const loadData = async () => {
    if (!sessionKey) return;
    setLoading(true);
    try {
      const res = await fetchContextInspect(sessionKey, token);
      setData(res);
      if (res?.rules) {
        setRules(res.rules);
      }
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (open) {
      loadData();
    }
  }, [open, sessionKey]);

  const toggleSection = async (key: string) => {
    const isExcluded = rules.system_sections.includes(key);
    const next = isExcluded
      ? rules.system_sections.filter((k) => k !== key)
      : [...rules.system_sections, key];
    const newRules = { ...rules, system_sections: next };
    setRules(newRules);
    await updateContextExclusions(sessionKey, client, { system_sections: next });
  };

  const toggleTool = async (name: string) => {
    const isExcluded = rules.tools.includes(name);
    const next = isExcluded
      ? rules.tools.filter((t) => t !== name)
      : [...rules.tools, name];
    const newRules = { ...rules, tools: next };
    setRules(newRules);
    await updateContextExclusions(sessionKey, client, { tools: next });
  };

  const toggleMessage = async (idx: number) => {
    const isExcluded = rules.message_idx.includes(idx);
    const next = isExcluded
      ? rules.message_idx.filter((i) => i !== idx)
      : [...rules.message_idx, idx];
    const newRules = { ...rules, message_idx: next };
    setRules(newRules);
    await updateContextExclusions(sessionKey, client, { message_idx: next });
  };

  const budget = data?.budget;
  const used = budget?.used ?? 0;
  const max = budget?.max ?? 128000;
  const pct = max > 0 ? Math.min(100, Math.round((used / max) * 100)) : 0;

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <TooltipProvider>
        <Tooltip>
          <TooltipTrigger asChild>
            <PopoverTrigger asChild>
              <Button
                variant="ghost"
                size="icon"
                aria-label="Context Window Inspector"
                className={cn(
                  "host-no-drag relative h-7 w-7 rounded-compact text-muted-foreground/85 hover:bg-accent/40 hover:text-foreground",
                  data?.available && "text-primary",
                )}
              >
                <Layers className="h-3.5 w-3.5" />
              </Button>
            </PopoverTrigger>
          </TooltipTrigger>
          <TooltipContent side="bottom" align="end">
            Context Window Inspector & Optimizer
          </TooltipContent>
        </Tooltip>
      </TooltipProvider>

      <PopoverContent
        align="end"
        sideOffset={8}
        className="w-[min(28rem,calc(100vw-1.5rem))] overflow-hidden p-0 shadow-lg"
      >
        <div className="flex max-h-[min(var(--radix-popover-content-available-height),36rem)] flex-col">
          {/* Header */}
          <div className="border-b border-border/45 bg-muted/30 px-4 py-3">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <span className="flex h-6 w-6 items-center justify-center rounded-md bg-primary/10 text-primary">
                  <Cpu className="h-3.5 w-3.5" />
                </span>
                <span className="text-[13px] font-semibold text-foreground">
                  Context Inspector & Optimizer
                </span>
              </div>
              <Button
                variant="ghost"
                size="icon"
                className="h-6 w-6 text-muted-foreground hover:text-foreground"
                onClick={loadData}
                disabled={loading}
              >
                <RefreshCw
                  className={cn("h-3.5 w-3.5", loading && "animate-spin")}
                />
              </Button>
            </div>
            {budget && (
              <p className="mt-1 text-[11px] text-muted-foreground">
                Model: <span className="font-medium text-foreground">{budget.model_id}</span> ({budget.provider})
              </p>
            )}
          </div>

          {/* Budget progress bar */}
          <div className="border-b border-border/45 bg-card px-4 py-2.5">
            <div className="flex items-center justify-between text-xs">
              <span className="font-medium text-muted-foreground">Context Used</span>
              <span className="tabular-nums font-semibold text-foreground">
                ~{fmtTokens(used)} / {fmtTokens(max)} ({pct}%)
              </span>
            </div>
            <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-secondary">
              <div
                className="h-full bg-primary transition-all duration-300"
                style={{ width: `${pct}%` }}
              />
            </div>
          </div>

          {/* Body */}
          <div className="min-h-0 flex-1 space-y-2.5 overflow-y-auto overscroll-contain p-3 text-xs">
            {!data?.available ? (
              <div className="flex flex-col items-center justify-center py-6 text-center text-muted-foreground">
                <Info className="mb-2 h-6 w-6 opacity-40" />
                <p>No prompt captured yet for this session.</p>
                <p className="text-[11px]">Send a message to see context breakdown.</p>
              </div>
            ) : (
              <>
                {/* 1. System Prompt Breakdown */}
                <div className="rounded-md border border-border/60 bg-card p-2 shadow-xs">
                  <button
                    type="button"
                    className="flex w-full items-center justify-between font-medium text-foreground"
                    onClick={() =>
                      setExpandedSections((prev) => ({
                        ...prev,
                        system: !prev.system,
                      }))
                    }
                  >
                    <div className="flex items-center gap-1.5">
                      <FileText className="h-3.5 w-3.5 text-blue-500" />
                      <span>System Prompt</span>
                    </div>
                    <div className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
                      <span>~{fmtTokens(data.system?.total_tokens || 0)}</span>
                      {expandedSections.system ? (
                        <ChevronDown className="h-3.5 w-3.5" />
                      ) : (
                        <ChevronRight className="h-3.5 w-3.5" />
                      )}
                    </div>
                  </button>
                  {expandedSections.system && (
                    <div className="mt-2 space-y-1.5 border-t border-border/40 pt-2">
                      {data.system?.sections?.map((sec) => {
                        const isExcluded = rules.system_sections.includes(sec.key);
                        return (
                          <div
                            key={sec.key}
                            className={cn(
                              "flex items-start justify-between rounded p-1.5 text-[11px] transition-colors",
                              isExcluded ? "bg-muted/20 opacity-60 line-through" : "bg-muted/40",
                            )}
                          >
                            <div className="flex items-start gap-1.5 min-w-0 pr-2">
                              {sec.removable && (
                                <button
                                  type="button"
                                  onClick={() => toggleSection(sec.key)}
                                  className="mt-0.5 shrink-0 text-muted-foreground hover:text-foreground"
                                >
                                  {isExcluded ? (
                                    <Square className="h-3.5 w-3.5" />
                                  ) : (
                                    <CheckSquare className="h-3.5 w-3.5 text-primary" />
                                  )}
                                </button>
                              )}
                              <div className="min-w-0">
                                <div className="font-medium text-foreground">
                                  {sec.label}
                                </div>
                                <div className="truncate text-muted-foreground/80">
                                  {sec.content_preview}
                                </div>
                              </div>
                            </div>
                            <span className="shrink-0 tabular-nums text-muted-foreground">
                              ~{fmtTokens(sec.tokens)}
                            </span>
                          </div>
                        );
                      })}
                    </div>
                  )}
                </div>

                {/* 2. Tools Breakdown */}
                <div className="rounded-md border border-border/60 bg-card p-2 shadow-xs">
                  <button
                    type="button"
                    className="flex w-full items-center justify-between font-medium text-foreground"
                    onClick={() =>
                      setExpandedSections((prev) => ({
                        ...prev,
                        tools: !prev.tools,
                      }))
                    }
                  >
                    <div className="flex items-center gap-1.5">
                      <Wrench className="h-3.5 w-3.5 text-amber-500" />
                      <span>Tools ({data.tools?.items?.length || 0})</span>
                    </div>
                    <div className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
                      <span>~{fmtTokens(data.tools?.total_tokens || 0)}</span>
                      {expandedSections.tools ? (
                        <ChevronDown className="h-3.5 w-3.5" />
                      ) : (
                        <ChevronRight className="h-3.5 w-3.5" />
                      )}
                    </div>
                  </button>
                  {expandedSections.tools && (
                    <div className="mt-2 space-y-1 border-t border-border/40 pt-2">
                      {data.tools?.items?.map((t) => {
                        const isExcluded = rules.tools.includes(t.name);
                        return (
                          <div
                            key={t.name}
                            className={cn(
                              "flex items-center justify-between rounded px-2 py-1 text-[11px]",
                              isExcluded ? "bg-muted/20 opacity-60 line-through" : "bg-muted/40",
                            )}
                          >
                            <div className="flex items-center gap-1.5">
                              <button
                                type="button"
                                onClick={() => toggleTool(t.name)}
                                className="shrink-0 text-muted-foreground hover:text-foreground"
                              >
                                {isExcluded ? (
                                  <Square className="h-3.5 w-3.5" />
                                ) : (
                                  <CheckSquare className="h-3.5 w-3.5 text-primary" />
                                )}
                              </button>
                              <span className="font-mono text-foreground">{t.name}</span>
                            </div>
                            <span className="tabular-nums text-muted-foreground">
                              ~{fmtTokens(t.tokens)}
                            </span>
                          </div>
                        );
                      })}
                    </div>
                  )}
                </div>

                {/* 3. Messages Breakdown */}
                <div className="rounded-md border border-border/60 bg-card p-2 shadow-xs">
                  <button
                    type="button"
                    className="flex w-full items-center justify-between font-medium text-foreground"
                    onClick={() =>
                      setExpandedSections((prev) => ({
                        ...prev,
                        messages: !prev.messages,
                      }))
                    }
                  >
                    <div className="flex items-center gap-1.5">
                      <MessageSquare className="h-3.5 w-3.5 text-emerald-500" />
                      <span>Messages ({data.messages?.items?.length || 0})</span>
                    </div>
                    <div className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
                      <span>~{fmtTokens(data.messages?.total_tokens || 0)}</span>
                      {expandedSections.messages ? (
                        <ChevronDown className="h-3.5 w-3.5" />
                      ) : (
                        <ChevronRight className="h-3.5 w-3.5" />
                      )}
                    </div>
                  </button>
                  {expandedSections.messages && (
                    <div className="mt-2 space-y-1.5 border-t border-border/40 pt-2">
                      {data.messages?.items?.map((m) => {
                        const isExcluded = rules.message_idx.includes(m.idx);
                        const isWasted = m.tool_use_ids?.some((id) =>
                          rules.wasted_ids.includes(id),
                        );
                        return (
                          <div
                            key={m.idx}
                            className={cn(
                              "flex items-start justify-between rounded p-1.5 text-[11px]",
                              isExcluded || isWasted ? "bg-muted/20 opacity-60 line-through" : "bg-muted/40",
                            )}
                          >
                            <div className="flex items-start gap-1.5 min-w-0 pr-2">
                              <button
                                type="button"
                                onClick={() => toggleMessage(m.idx)}
                                className="mt-0.5 shrink-0 text-muted-foreground hover:text-foreground"
                              >
                                {isExcluded ? (
                                  <Square className="h-3.5 w-3.5" />
                                ) : (
                                  <CheckSquare className="h-3.5 w-3.5 text-primary" />
                                )}
                              </button>
                              <div className="min-w-0">
                                <div>
                                  <span className="font-semibold uppercase text-foreground/80">
                                    {m.role}:
                                  </span>{" "}
                                  <span className="text-muted-foreground">{m.preview}</span>
                                </div>
                                {isWasted && (
                                  <span className="mt-0.5 inline-block rounded bg-amber-500/10 px-1 py-0.2 text-[9px] font-semibold text-amber-600 dark:text-amber-400">
                                    wasted
                                  </span>
                                )}
                              </div>
                            </div>
                            <span className="shrink-0 tabular-nums text-muted-foreground">
                              ~{fmtTokens(m.tokens)}
                            </span>
                          </div>
                        );
                      })}
                    </div>
                  )}
                </div>
              </>
            )}
          </div>
        </div>
      </PopoverContent>
    </Popover>
  );
}

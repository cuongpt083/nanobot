import { Bot, Brain, Code2, Users } from "lucide-react";
import type { ComponentType } from "react";
import { useTranslation } from "react-i18next";

import { cn } from "@/lib/utils";
import type {
  CoworkerParticipant,
  CoworkerParticipantKind,
  CoworkerParticipantState,
} from "@/lib/types";

const KIND_ICON: Record<CoworkerParticipantKind, ComponentType<{ className?: string }>> = {
  coordinator: Bot,
  advisor: Brain,
  teammate: Users,
  coding: Code2,
};

const KIND_TONE: Record<CoworkerParticipantKind, string> = {
  coordinator: "text-primary",
  advisor: "text-violet-600 dark:text-violet-400",
  teammate: "text-sky-600 dark:text-sky-400",
  coding: "text-emerald-600 dark:text-emerald-400",
};

const STATE_DOT: Record<CoworkerParticipantState, string> = {
  idle: "bg-muted-foreground/40",
  queued: "bg-sky-500",
  working: "bg-emerald-500",
  waiting: "bg-amber-500",
  done: "bg-emerald-600",
  error: "bg-red-500",
  paused: "bg-muted-foreground/60",
};

const STATE_BADGE: Record<CoworkerParticipantState, string> = {
  idle: "bg-muted text-muted-foreground",
  queued: "bg-sky-500/10 text-sky-600 dark:text-sky-400",
  working: "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400",
  waiting: "bg-amber-500/10 text-amber-600 dark:text-amber-400",
  done: "bg-emerald-500/10 text-emerald-700 dark:text-emerald-300",
  error: "bg-red-500/10 text-red-600 dark:text-red-400",
  paused: "bg-muted text-muted-foreground",
};

/** Participants worth surfacing: everything except an idle coordinator / idle teammates. */
export function visibleParticipants(
  participants: CoworkerParticipant[] | undefined,
): CoworkerParticipant[] {
  return (participants ?? []).filter((p) => p.state !== "idle");
}

export function formatElapsed(sinceSeconds: number | null, nowMs: number = Date.now()): string {
  if (sinceSeconds === null) return "";
  const seconds = Math.max(0, Math.floor(nowMs / 1000 - sinceSeconds));
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m`;
  return `${Math.floor(minutes / 60)}h${String(minutes % 60).padStart(2, "0")}m`;
}

function StateDot({ state }: { state: CoworkerParticipantState }) {
  return (
    <span className="relative flex h-2 w-2 shrink-0" aria-hidden="true">
      {state === "working" ? (
        <span
          className={cn(
            "absolute inline-flex h-full w-full animate-ping rounded-full opacity-70",
            STATE_DOT[state],
          )}
        />
      ) : null}
      <span className={cn("relative inline-flex h-2 w-2 rounded-full", STATE_DOT[state])} />
    </span>
  );
}

/** Compact chips in the thread header; clicking one opens the inspector. */
export function CoworkerParticipantsStrip({
  participants,
  onSelect,
}: {
  participants: CoworkerParticipant[] | undefined;
  onSelect?: (participant: CoworkerParticipant) => void;
}) {
  const { t } = useTranslation();
  const shown = visibleParticipants(participants);
  if (shown.length === 0) return null;
  return (
    <ul
      aria-label={t("coworker.participants.stripLabel", {
        defaultValue: "Agents taking part in this session",
      })}
      className="host-no-drag mr-1 flex min-w-0 max-w-[min(28rem,45vw)] items-center gap-1 overflow-x-auto"
    >
      {shown.map((p) => {
        const Icon = KIND_ICON[p.kind];
        const stateLabel = t(`coworker.participants.state.${p.state}`, { defaultValue: p.state });
        return (
          <li key={`${p.kind}:${p.id}`} className="shrink-0">
            <button
              type="button"
              data-participant={p.id}
              data-state={p.state}
              title={[p.label, stateLabel, p.task].filter(Boolean).join(" · ")}
              onClick={() => onSelect?.(p)}
              className="inline-flex h-6 items-center gap-1.5 rounded-full border border-border/60 bg-card px-2 text-[11px] text-foreground/90 hover:bg-accent/40"
            >
              <StateDot state={p.state} />
              <Icon className={cn("h-3 w-3", KIND_TONE[p.kind])} />
              <span className="max-w-[7rem] truncate">{p.label}</span>
            </button>
          </li>
        );
      })}
    </ul>
  );
}

function participantMeta(
  p: CoworkerParticipant,
  t: (key: string, options?: Record<string, unknown>) => string,
): string[] {
  const parts: string[] = [];
  if (p.kind === "coding") {
    if (p.detail.tools) {
      parts.push(t("coworker.participants.tools", { count: p.detail.tools, defaultValue: `${p.detail.tools} tools` }));
    }
    if (p.detail.last_tool) parts.push(p.detail.last_tool);
    if ((p.detail.rounds ?? 1) > 1) {
      parts.push(t("coworker.participants.rounds", { count: p.detail.rounds, defaultValue: `round ${p.detail.rounds}` }));
    }
  }
  if (p.kind === "advisor" && p.detail.max_uses !== undefined) {
    parts.push(
      t("coworker.participants.uses", {
        used: p.detail.uses ?? 0,
        max: p.detail.max_uses,
        defaultValue: `${p.detail.uses ?? 0}/${p.detail.max_uses} consults`,
      }),
    );
  }
  return parts;
}

/** Detailed list used inside the inspector. Shows every participant, idle ones muted. */
export function CoworkerParticipantList({
  participants,
  highlightId,
}: {
  participants: CoworkerParticipant[] | undefined;
  highlightId?: string | null;
}) {
  const { t } = useTranslation();
  const all = participants ?? [];
  if (all.length === 0) {
    return (
      <p className="text-[11px] text-muted-foreground">
        {t("coworker.participants.empty", { defaultValue: "No other agents are involved yet." })}
      </p>
    );
  }
  return (
    <ul className="space-y-1.5">
      {all.map((p) => {
        const Icon = KIND_ICON[p.kind];
        const meta = participantMeta(p, t);
        const elapsed = p.state === "working" || p.state === "waiting" ? formatElapsed(p.since) : "";
        return (
          <li
            key={`${p.kind}:${p.id}`}
            data-participant={p.id}
            className={cn(
              "rounded-md border border-border/50 bg-muted/20 p-2 text-[11px]",
              p.state === "idle" && "opacity-60",
              highlightId === p.id && "ring-1 ring-primary/50",
            )}
          >
            <div className="flex items-center justify-between gap-2">
              <span className="flex min-w-0 items-center gap-1.5 font-medium text-foreground">
                <StateDot state={p.state} />
                <Icon className={cn("h-3.5 w-3.5 shrink-0", KIND_TONE[p.kind])} />
                <span className="truncate">{p.label}</span>
              </span>
              <span
                className={cn(
                  "shrink-0 rounded-full px-1.5 py-0.5 text-[10px] font-semibold uppercase",
                  STATE_BADGE[p.state],
                )}
              >
                {t(`coworker.participants.state.${p.state}`, { defaultValue: p.state })}
                {elapsed ? ` · ${elapsed}` : ""}
              </span>
            </div>
            <div className="mt-0.5 flex flex-wrap items-center gap-x-2 text-[10.5px] text-muted-foreground">
              <span className="font-mono">{p.engine}</span>
              {meta.map((m) => (
                <span key={m}>{m}</span>
              ))}
            </div>
            {p.task ? (
              <div className="mt-1 line-clamp-2 text-muted-foreground">{p.task}</div>
            ) : null}
            {p.kind === "coding" && p.detail.diffstat ? (
              <div className="mt-0.5 font-mono text-[10.5px] text-muted-foreground">
                {p.detail.diffstat.split("\n").pop()}
              </div>
            ) : null}
            {p.kind === "advisor" && p.detail.last_consult ? (
              <div className="mt-1 text-muted-foreground">
                {t("coworker.participants.lastConsult", { defaultValue: "Last consult" })}:{" "}
                {p.detail.last_consult.ok
                  ? t("coworker.participants.consultOk", { defaultValue: "advice given" })
                  : t("coworker.participants.consultFailed", { defaultValue: "failed" })}
                {" · "}
                {Math.round(p.detail.last_consult.duration_ms / 100) / 10}s
                {p.detail.last_consult.focus ? ` · ${p.detail.last_consult.focus}` : ""}
              </div>
            ) : null}
          </li>
        );
      })}
    </ul>
  );
}

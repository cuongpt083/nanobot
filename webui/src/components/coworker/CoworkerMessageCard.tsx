import { useState } from "react";
import {
  Brain,
  ChevronDown,
  ChevronRight,
  Code2,
  GitBranch,
  Sparkles,
  Users,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import { MarkdownText } from "@/components/MarkdownText";


export type CoworkerCardKind = "advisor" | "room" | "coding";

export interface CoworkerCardData {
  kind: CoworkerCardKind;
  target?: string;
  body: string;
}

export function parseCoworkerMessage(text: string): CoworkerCardData | null {
  const trimmed = text.trim();
  if (trimmed.startsWith("[auto-advisor-review]")) {
    const body = trimmed.replace(/^\[auto-advisor-review\]\s*/, "").trim();
    return {
      kind: "advisor",
      body: body || "Conduct strategic checkpoint review of recent progress and next steps.",
    };
  }

  if (trimmed.startsWith("[auto-room]")) {
    const raw = trimmed.replace(/^\[auto-room\]\s*/, "").trim();
    const mentionMatch = raw.match(/^@([a-zA-Z0-9_-]+)\s*([\s\S]*)$/);
    if (mentionMatch) {
      return {
        kind: "room",
        target: `@${mentionMatch[1]}`,
        body: mentionMatch[2]?.trim() || "",
      };
    }
    return {
      kind: "room",
      body: raw,
    };
  }

  if (trimmed.startsWith("[auto-coding-result]")) {
    const raw = trimmed.replace(/^\[auto-coding-result\]\s*/, "").trim();
    const taskMatch = raw.match(/\b(ct-[a-zA-Z0-9_-]+)\b/);
    return {
      kind: "coding",
      target: taskMatch ? taskMatch[1] : undefined,
      body: raw,
    };
  }

  return null;
}

export function CoworkerMessageCard({
  data,
  onOpenFilePreview,
}: {
  data: CoworkerCardData;
  onOpenFilePreview?: (path: string) => void;
}) {
  const { t } = useTranslation();
  const [expanded, setExpanded] = useState(false);

  if (data.kind === "advisor") {
    return (
      <div className="my-2 w-full max-w-2xl rounded-xl border border-violet-500/30 bg-violet-50/50 p-3.5 shadow-sm dark:border-violet-500/20 dark:bg-violet-950/20">
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-violet-500/15 text-violet-600 dark:text-violet-400">
              <Brain className="h-4 w-4" />
            </span>
            <span className="text-xs font-semibold uppercase tracking-wider text-violet-700 dark:text-violet-300">
              {t("coworker.advisor.reviewTitle", { defaultValue: "Senior Advisor Review" })}
            </span>
            <span className="inline-flex items-center gap-1 rounded-full bg-violet-500/10 px-2 py-0.5 text-[11px] font-medium text-violet-700 dark:text-violet-300">
              <Sparkles className="h-3 w-3" />
              {t("coworker.advisor.automated", { defaultValue: "Checkpoint" })}
            </span>
          </div>
          <button
            type="button"
            onClick={() => setExpanded(!expanded)}
            className="inline-flex items-center gap-1 text-[11px] font-medium text-violet-600/80 hover:text-violet-700 dark:text-violet-400"
          >
            {expanded ? (
              <ChevronDown className="h-3.5 w-3.5" />
            ) : (
              <ChevronRight className="h-3.5 w-3.5" />
            )}
          </button>
        </div>

        {expanded ? (
          <div className="mt-2.5 border-t border-violet-500/15 pt-2 text-xs leading-relaxed text-foreground/90">
            <MarkdownText onOpenFilePreview={onOpenFilePreview}>{data.body}</MarkdownText>
          </div>
        ) : (
          <p className="mt-1.5 line-clamp-2 text-xs text-muted-foreground">
            {data.body}
          </p>
        )}
      </div>
    );
  }

  if (data.kind === "room") {
    return (
      <div className="my-2 w-full max-w-2xl rounded-xl border border-sky-500/30 bg-sky-50/50 p-3.5 shadow-sm dark:border-sky-500/20 dark:bg-sky-950/20">
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-sky-500/15 text-sky-600 dark:text-sky-400">
              <Users className="h-4 w-4" />
            </span>
            <span className="text-xs font-semibold uppercase tracking-wider text-sky-700 dark:text-sky-300">
              {t("coworker.room.handoffTitle", { defaultValue: "Room Teammate Handoff" })}
            </span>
            {data.target ? (
              <span className="inline-flex items-center rounded-full bg-sky-500/10 px-2 py-0.5 text-[11px] font-medium text-sky-700 dark:text-sky-300">
                {data.target}
              </span>
            ) : null}
          </div>
        </div>

        <div className="mt-2 text-xs leading-relaxed text-foreground/90">
          <MarkdownText onOpenFilePreview={onOpenFilePreview}>{data.body}</MarkdownText>
        </div>
      </div>
    );
  }

  if (data.kind === "coding") {
    return (
      <div className="my-2 w-full max-w-2xl rounded-xl border border-emerald-500/30 bg-emerald-50/50 p-3.5 shadow-sm dark:border-emerald-500/20 dark:bg-emerald-950/20">
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-emerald-500/15 text-emerald-600 dark:text-emerald-400">
              <Code2 className="h-4 w-4" />
            </span>
            <span className="text-xs font-semibold uppercase tracking-wider text-emerald-700 dark:text-emerald-300">
              {t("coworker.coding.resultTitle", { defaultValue: "Coding Task Result" })}
            </span>
            {data.target ? (
              <span className="inline-flex items-center gap-1 rounded-full bg-emerald-500/10 px-2 py-0.5 text-[11px] font-mono font-medium text-emerald-700 dark:text-emerald-300">
                <GitBranch className="h-3 w-3" />
                {data.target}
              </span>
            ) : null}
          </div>
          <button
            type="button"
            onClick={() => setExpanded(!expanded)}
            className="inline-flex items-center gap-1 text-[11px] font-medium text-emerald-600/80 hover:text-emerald-700 dark:text-emerald-400"
          >
            {expanded ? (
              <ChevronDown className="h-3.5 w-3.5" />
            ) : (
              <ChevronRight className="h-3.5 w-3.5" />
            )}
          </button>
        </div>

        {expanded ? (
          <div className="mt-2.5 border-t border-emerald-500/15 pt-2 text-xs leading-relaxed text-foreground/90">
            <MarkdownText onOpenFilePreview={onOpenFilePreview}>{data.body}</MarkdownText>
          </div>
        ) : (
          <p className="mt-1.5 line-clamp-2 text-xs font-mono text-muted-foreground">
            {data.body}
          </p>
        )}
      </div>
    );
  }

  return null;
}

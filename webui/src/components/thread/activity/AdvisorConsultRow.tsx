import { useState } from "react";
import { AlertCircle, Brain, ChevronDown, ChevronUp, Clock } from "lucide-react";
import { useTranslation } from "react-i18next";

import { MarkdownText } from "@/components/MarkdownText";
import { ActivityStep } from "@/components/thread/activity/ActivityStep";
import type { AdvisorConsultRunModel } from "@/components/thread/activity/advisor-consult-model";
import { cn } from "@/lib/utils";

export function AdvisorConsultRow({
  run,
  turnActive,
}: {
  run: AdvisorConsultRunModel;
  turnActive: boolean;
}) {
  const { t } = useTranslation();
  const [expanded, setExpanded] = useState(false);

  // 1. Running state
  if (run.status === "running") {
    const active = turnActive;
    const label = run.focus
      ? t("coworker.advisorConsult.runningFocus", {
          focus: run.focus,
          defaultValue: `Đang hỏi advisor · ${run.focus}`,
        })
      : t("coworker.advisorConsult.running", {
          defaultValue: "Đang hỏi advisor",
        });

    return (
      <ActivityStep
        icon={Clock}
        active={active}
        tone="active"
        label={label}
      />
    );
  }

  // 2. Advice state
  if (run.parsed?.kind === "advice") {
    const { model, n, max, text } = run.parsed;
    const lines = text.split("\n").length;
    const hasToggle = lines > 4 || text.length > 240;

    return (
      <div
        data-testid="advisor-consult-card"
        className="my-1.5 rounded-lg border bg-card/60 p-3 text-sm shadow-xs space-y-2 text-foreground"
      >
        <div className="flex items-center justify-between gap-2 text-xs">
          <div className="flex items-center gap-1.5 font-medium min-w-0 truncate">
            <Brain className="h-3.5 w-3.5 shrink-0 text-primary" />
            <span className="truncate" data-testid="advisor-consult-focus">
              {run.focus || t("coworker.advisorConsult.title", { defaultValue: "Advisor" })}
            </span>
          </div>
          <div className="flex items-center gap-1.5 shrink-0 text-[11px] text-muted-foreground">
            <span
              data-testid="advisor-consult-budget"
              className="rounded bg-muted px-1.5 py-0.5 font-mono"
            >
              {n}/{max}
            </span>
            <span
              data-testid="advisor-consult-model"
              className="rounded bg-muted px-1.5 py-0.5"
            >
              {model}
            </span>
          </div>
        </div>

        <div
          data-testid="advisor-consult-text"
          className={cn(
            "text-xs text-muted-foreground transition-all",
            !expanded && "line-clamp-4",
          )}
        >
          <MarkdownText>{text}</MarkdownText>
        </div>

        {hasToggle && (
          <button
            type="button"
            data-testid="advisor-consult-toggle"
            onClick={() => setExpanded(!expanded)}
            className="flex items-center gap-1 text-[11px] text-primary hover:underline font-medium cursor-pointer"
          >
            {expanded ? (
              <>
                <ChevronUp className="h-3 w-3" />
                {t("coworker.advisorConsult.collapse", { defaultValue: "Thu gọn" })}
              </>
            ) : (
              <>
                <ChevronDown className="h-3 w-3" />
                {t("coworker.advisorConsult.expand", { defaultValue: "Xem thêm" })}
              </>
            )}
          </button>
        )}
      </div>
    );
  }

  // 3. Status chip state
  const statusKey = run.parsed?.kind === "status" ? run.parsed.status : "advisor_error";
  let statusText = "";
  let isError = run.status === "error" || statusKey === "advisor_error";

  if (statusKey === "insufficient_context") {
    statusText = t("coworker.advisorConsult.statusInsufficientContext", {
      defaultValue: "chưa đủ ngữ cảnh",
    });
  } else if (statusKey === "max_uses_exceeded") {
    statusText = t("coworker.advisorConsult.statusMaxUsesExceeded", {
      defaultValue: "hết ngân sách",
    });
  } else if (statusKey === "advisor_disabled") {
    statusText = t("coworker.advisorConsult.statusAdvisorDisabled", {
      defaultValue: "chưa cấu hình advisor",
    });
  } else {
    statusText = t("coworker.advisorConsult.statusAdvisorError", {
      defaultValue: "lỗi advisor",
    });
    isError = true;
  }

  const prefix = run.focus ? `${run.focus} · ` : "";
  const label = (
    <span className="flex items-center gap-1.5">
      {prefix && <span>{prefix}</span>}
      <span
        data-testid="advisor-status-chip"
        className={cn(
          "inline-flex items-center rounded px-1.5 py-0.5 text-[11px] font-medium border",
          isError
            ? "border-destructive/30 bg-destructive/10 text-destructive"
            : "border-border bg-muted text-muted-foreground",
        )}
      >
        {statusText}
      </span>
    </span>
  );

  return (
    <ActivityStep
      icon={isError ? AlertCircle : Brain}
      tone={isError ? "error" : "neutral"}
      label={label}
    />
  );
}

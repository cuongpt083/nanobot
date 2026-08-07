import { useState, useCallback } from "react";
import { ThumbsUp, ThumbsDown, RotateCcw, Lightbulb } from "lucide-react";
import { useTranslation } from "react-i18next";
import { cn } from "@/lib/utils";

export interface AssistantFeedbackActionsProps {
  turnId: string;
  onFeedback?: (kind: "helpful" | "incorrect" | "retry" | "explain_more") => void;
  disabled?: boolean;
}

export function AssistantFeedbackActions({
  turnId,
  onFeedback,
  disabled = false,
}: AssistantFeedbackActionsProps) {
  const { t } = useTranslation();
  const [selected, setSelected] = useState<"helpful" | "incorrect" | "retry" | "explain_more" | null>(null);

  const handleClick = useCallback(
    (kind: "helpful" | "incorrect" | "retry" | "explain_more") => {
      if (disabled) return;
      setSelected(kind);
      onFeedback?.(kind);
    },
    [disabled, onFeedback]
  );

  if (!turnId) return null;

  return (
    <div className="flex items-center space-x-1 mt-2 text-xs text-muted-foreground" data-testid="assistant-feedback-actions">
      <button
        type="button"
        disabled={disabled || selected !== null}
        onClick={() => handleClick("helpful")}
        className={cn(
          "p-1 rounded hover:bg-accent hover:text-accent-foreground transition-colors",
          selected === "helpful" && "text-emerald-500 font-bold"
        )}
        title={t("feedback.helpful", "Helpful")}
        aria-label="Helpful"
      >
        <ThumbsUp className="w-3.5 h-3.5" />
      </button>
      <button
        type="button"
        disabled={disabled || selected !== null}
        onClick={() => handleClick("incorrect")}
        className={cn(
          "p-1 rounded hover:bg-accent hover:text-accent-foreground transition-colors",
          selected === "incorrect" && "text-rose-500 font-bold"
        )}
        title={t("feedback.incorrect", "Incorrect")}
        aria-label="Incorrect"
      >
        <ThumbsDown className="w-3.5 h-3.5" />
      </button>
      <button
        type="button"
        disabled={disabled}
        onClick={() => handleClick("retry")}
        className="p-1 rounded hover:bg-accent hover:text-accent-foreground transition-colors"
        title={t("feedback.retry", "Retry")}
        aria-label="Retry"
      >
        <RotateCcw className="w-3.5 h-3.5" />
      </button>
      <button
        type="button"
        disabled={disabled}
        onClick={() => handleClick("explain_more")}
        className="p-1 rounded hover:bg-accent hover:text-accent-foreground transition-colors"
        title={t("feedback.explain_more", "Explain More")}
        aria-label="Explain More"
      >
        <Lightbulb className="w-3.5 h-3.5" />
      </button>
    </div>
  );
}

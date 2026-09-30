import { useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import { useTranslation } from "react-i18next";

import { cn } from "@/lib/utils";
import type { CoworkerAdvisorExchange } from "@/lib/types";

interface CoworkerAdvisorExchangesProps {
  exchanges: CoworkerAdvisorExchange[] | undefined;
  className?: string;
}

function formatClock(atSeconds: number): string {
  return new Date(atSeconds * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

/**
 * What the executor asked the advisor and what it got back, newest first.
 * The question is the `focus` the executor passed; the advisor also saw the whole conversation.
 */
export function CoworkerAdvisorExchanges({ exchanges, className }: CoworkerAdvisorExchangesProps) {
  const { t } = useTranslation();
  const [openIndex, setOpenIndex] = useState<number | null>(0);
  const items = [...(exchanges ?? [])].reverse();

  if (items.length === 0) {
    return (
      <p className={cn("text-[11px] text-muted-foreground", className)}>
        {t("coworker.advisorExchanges.empty", {
          defaultValue: "No consults yet. The agent asks the advisor when it needs a second opinion.",
        })}
      </p>
    );
  }

  return (
    <ul className={cn("space-y-1.5", className)} aria-label={t("coworker.advisorExchanges.title", { defaultValue: "Advisor Q&A" })}>
      {items.map((exchange, index) => {
        const open = openIndex === index;
        const Chevron = open ? ChevronDown : ChevronRight;
        return (
          <li key={`${exchange.at}-${exchange.n}`} className="rounded-md border border-border/50 bg-muted/20">
            <button
              type="button"
              aria-expanded={open}
              onClick={() => setOpenIndex(open ? null : index)}
              className="flex w-full items-start gap-1.5 px-2 py-1.5 text-left"
            >
              <Chevron className="mt-0.5 h-3 w-3 shrink-0 text-muted-foreground" aria-hidden />
              <span className="min-w-0 flex-1">
                <span className="block text-[11px] font-medium text-foreground">
                  {exchange.focus
                    || t("coworker.advisorExchanges.noFocus", { defaultValue: "Reviewed the whole session" })}
                </span>
                <span className="block text-[10.5px] text-muted-foreground">
                  #{exchange.n} · {exchange.model} · {formatClock(exchange.at)}
                </span>
              </span>
            </button>
            {open ? (
              <div className="border-t border-border/40 px-2 py-1.5">
                <p className="whitespace-pre-wrap break-words text-[11.5px] leading-relaxed text-foreground/90">
                  {exchange.advice}
                </p>
              </div>
            ) : null}
          </li>
        );
      })}
    </ul>
  );
}

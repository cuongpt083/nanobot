import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import {
  parseAdvisorResult,
  type AdvisorConsultRunModel,
} from "@/components/thread/activity/advisor-consult-model";
import { AdvisorConsultRow } from "@/components/thread/activity/AdvisorConsultRow";

describe("parseAdvisorResult", () => {
  it("parses valid advisor advice format", () => {
    const raw =
      "ADVISOR (claude-3-7-sonnet) — advice 2/10:\n\n" +
      "Consider using an event-driven queue instead of direct RPC calls.\n\n---\n" +
      "(Reminder: consult the advisor again when the same error recurs...)";
    const result = parseAdvisorResult(raw);
    expect(result).not.toBeNull();
    expect(result?.kind).toBe("advice");
    if (result?.kind === "advice") {
      expect(result.model).toBe("claude-3-7-sonnet");
      expect(result.n).toBe(2);
      expect(result.max).toBe(10);
      expect(result.text).toBe("Consider using an event-driven queue instead of direct RPC calls.");
    }
  });

  it("parses status payload from JSON string or object", () => {
    const jsonStr = JSON.stringify({
      status: "insufficient_context",
      fallback: "Orient first: locate and read key files.",
    });
    const result1 = parseAdvisorResult(jsonStr);
    expect(result1).not.toBeNull();
    expect(result1?.kind).toBe("status");
    if (result1?.kind === "status") {
      expect(result1.status).toBe("insufficient_context");
      expect(result1.fallback).toBe("Orient first: locate and read key files.");
    }

    const obj = {
      status: "max_uses_exceeded",
      uses: 10,
      maxUses: 10,
      fallback: "Advisor budget is spent.",
    };
    const result2 = parseAdvisorResult(obj);
    expect(result2).not.toBeNull();
    expect(result2?.kind).toBe("status");
    if (result2?.kind === "status") {
      expect(result2.status).toBe("max_uses_exceeded");
      expect(result2.fallback).toBe("Advisor budget is spent.");
    }
  });

  it("returns null for garbage or unrecognized result", () => {
    expect(parseAdvisorResult("random error output that is not json")).toBeNull();
    expect(parseAdvisorResult(12345)).toBeNull();
    expect(parseAdvisorResult(null)).toBeNull();
    expect(parseAdvisorResult(undefined)).toBeNull();
    expect(parseAdvisorResult({})).toBeNull();
  });
});

describe("AdvisorConsultRow rendering", () => {
  it("renders running state with clock and focus", () => {
    const run: AdvisorConsultRunModel = {
      key: "adv:1",
      focus: "Review database design",
      status: "running",
    };
    render(<AdvisorConsultRow run={run} turnActive={true} />);
    expect(screen.getByText(/Review database design/i)).toBeInTheDocument();
    expect(screen.getByTestId("activity-step")).toBeInTheDocument();
  });

  it("renders advice card with focus, budget, model, and advice text", () => {
    const run: AdvisorConsultRunModel = {
      key: "adv:2",
      focus: "Refactor async handler",
      status: "done",
      parsed: {
        kind: "advice",
        model: "o3-mini",
        n: 3,
        max: 5,
        text: "Split the handler into separate ingestion and validation steps.",
      },
    };
    render(<AdvisorConsultRow run={run} turnActive={false} />);
    expect(screen.getByTestId("advisor-consult-card")).toBeInTheDocument();
    expect(screen.getByTestId("advisor-consult-focus")).toHaveTextContent("Refactor async handler");
    expect(screen.getByTestId("advisor-consult-budget")).toHaveTextContent("3/5");
    expect(screen.getByTestId("advisor-consult-model")).toHaveTextContent("o3-mini");
    expect(screen.getByTestId("advisor-consult-text")).toHaveTextContent(
      "Split the handler into separate ingestion and validation steps.",
    );
  });

  it("renders status chips for insufficient_context, max_uses_exceeded, and advisor_error", () => {
    const runInsufficient: AdvisorConsultRunModel = {
      key: "adv:3",
      focus: "Fix bug",
      status: "done",
      parsed: {
        kind: "status",
        status: "insufficient_context",
      },
    };
    const { unmount: unmount1 } = render(
      <AdvisorConsultRow run={runInsufficient} turnActive={false} />,
    );
    expect(screen.getByTestId("advisor-status-chip")).toBeInTheDocument();
    unmount1();

    const runMaxUses: AdvisorConsultRunModel = {
      key: "adv:4",
      status: "done",
      parsed: {
        kind: "status",
        status: "max_uses_exceeded",
      },
    };
    const { unmount: unmount2 } = render(
      <AdvisorConsultRow run={runMaxUses} turnActive={false} />,
    );
    expect(screen.getByTestId("advisor-status-chip")).toBeInTheDocument();
    unmount2();

    const runError: AdvisorConsultRunModel = {
      key: "adv:5",
      status: "error",
      error: "Connection timeout",
    };
    render(<AdvisorConsultRow run={runError} turnActive={false} />);
    expect(screen.getByTestId("advisor-status-chip")).toBeInTheDocument();
  });
});

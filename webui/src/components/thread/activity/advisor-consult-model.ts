import { canonicalToolTrace, formatToolCallTrace } from "@/lib/tool-traces";
import type { ToolProgressEvent } from "@/lib/types";
import { safeActivityDetail } from "./activity-text";

export type AdvisorParsedAdvice = {
  kind: "advice";
  model: string;
  n: number;
  max: number;
  text: string;
};

export type AdvisorParsedStatus = {
  kind: "status";
  status: string;
  fallback?: string;
};

export type AdvisorParsedResult = AdvisorParsedAdvice | AdvisorParsedStatus;

export type AdvisorConsultStatus = "running" | "done" | "error";

export interface AdvisorConsultRunModel {
  key: string;
  focus?: string;
  status: AdvisorConsultStatus;
  parsed?: AdvisorParsedResult | null;
  error?: string;
}

const ADVISOR_ADVICE_RE = /^ADVISOR \((.+?)\) — advice (\d+)\/(\d+):\n\n([\s\S]*?)(?:\n\n---\n|$)/;

export function parseAdvisorResult(result: unknown): AdvisorParsedResult | null {
  if (result == null) return null;

  let raw = "";
  if (typeof result === "string") {
    raw = result;
  } else if (typeof result === "object" && result !== null) {
    const rec = result as Record<string, unknown>;
    if (typeof rec.status === "string") {
      return {
        kind: "status",
        status: rec.status,
        fallback: typeof rec.fallback === "string" ? rec.fallback : undefined,
      };
    }
    if (typeof rec.content === "string") {
      raw = rec.content;
    } else if (typeof rec.text === "string") {
      raw = rec.text;
    }
  }

  if (raw) {
    const match = ADVISOR_ADVICE_RE.exec(raw);
    if (match) {
      return {
        kind: "advice",
        model: match[1],
        n: parseInt(match[2], 10),
        max: parseInt(match[3], 10),
        text: match[4].trim(),
      };
    }
    try {
      const parsed = JSON.parse(raw);
      if (parsed && typeof parsed === "object" && typeof (parsed as Record<string, unknown>).status === "string") {
        const p = parsed as Record<string, unknown>;
        return {
          kind: "status",
          status: String(p.status),
          fallback: typeof p.fallback === "string" ? p.fallback : undefined,
        };
      }
    } catch {
      // not JSON
    }
  }

  return null;
}

const ADVISOR_STATUS_RANK: Record<AdvisorConsultStatus, number> = {
  running: 1,
  done: 2,
  error: 3,
};

export function advisorRunsByTraceLine(
  events: ToolProgressEvent[],
): Map<string, AdvisorConsultRunModel> {
  const runs = new Map<string, AdvisorConsultRunModel>();
  for (const event of events) {
    const run = advisorRunFromEvent(event);
    const line = run ? formatToolCallTrace(event) : null;
    if (!run || !line) continue;
    const key = canonicalToolTrace(line);
    runs.set(key, mergeAdvisorConsultRun(runs.get(key), run));
  }
  return runs;
}

function advisorRunFromEvent(event: ToolProgressEvent): AdvisorConsultRunModel | null {
  const name = compactToolName(toolEventName(event));
  if (name !== "advisor") return null;

  const args = toolEventArguments(event);
  const focus = stringField(args, ["focus", "question", "prompt"]);
  const status: AdvisorConsultStatus =
    event.phase === "error"
      ? "error"
      : event.phase === "end"
        ? "done"
        : "running";

  const parsed = event.result != null ? parseAdvisorResult(event.result) : null;

  return {
    key: event.call_id ? `call:${event.call_id}` : formatToolCallTrace(event) ?? `advisor:${focus}`,
    focus: focus || undefined,
    status,
    parsed,
    error: status === "error" ? readableError(event.error) : undefined,
  };
}

function mergeAdvisorConsultRun(
  existing: AdvisorConsultRunModel | undefined,
  incoming: AdvisorConsultRunModel,
): AdvisorConsultRunModel {
  if (!existing) return incoming;
  if (ADVISOR_STATUS_RANK[incoming.status] < ADVISOR_STATUS_RANK[existing.status]) {
    return existing;
  }
  return {
    ...existing,
    ...incoming,
    focus: incoming.focus || existing.focus,
    parsed: incoming.parsed ?? existing.parsed,
    error: incoming.error ?? existing.error,
  };
}

export function parseAdvisorRunTrace(line: string): AdvisorConsultRunModel | null {
  const trimmed = line.trim();
  const match = /^([a-zA-Z0-9_.-]+)\((.*)\)$/.exec(trimmed);
  if (!match) return null;
  const name = compactToolName(match[1]);
  if (name !== "advisor") return null;

  let focus: string | undefined;
  try {
    const parsedArgs = JSON.parse(match[2]);
    focus = stringField(parsedArgs, ["focus", "question", "prompt"]) || undefined;
  } catch {
    // ignore
  }

  return {
    key: canonicalToolTrace(line),
    focus,
    status: "done",
  };
}

function compactToolName(name: string): string {
  return name.toLowerCase().split(".").pop() || name.toLowerCase();
}

function toolEventName(event: ToolProgressEvent): string {
  const functionName = (event as { function?: { name?: unknown } }).function?.name;
  if (typeof functionName === "string") return functionName;
  return typeof event.name === "string" ? event.name : "";
}

function toolEventArguments(event: ToolProgressEvent): unknown {
  const functionArgs = (event as { function?: { arguments?: unknown } }).function?.arguments;
  const raw = functionArgs ?? event.arguments;
  if (typeof raw !== "string") return raw ?? {};
  try {
    return raw.trim() ? JSON.parse(raw) : {};
  } catch {
    return {};
  }
}

function stringField(value: unknown, keys: string[]): string {
  if (!value || typeof value !== "object" || Array.isArray(value)) return "";
  const record = value as Record<string, unknown>;
  for (const key of keys) {
    const field = record[key];
    if (typeof field === "string" && field.trim()) return field.trim();
  }
  return "";
}

function readableError(error: unknown): string | undefined {
  if (typeof error === "string" && error.trim()) return safeActivityDetail(error, 240);
  if (!error) return undefined;
  try {
    return safeActivityDetail(JSON.stringify(error), 240);
  } catch {
    return "Advisor consultation failed";
  }
}

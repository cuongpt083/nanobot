import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/providers/ClientProvider", () => ({
  useClient: () => ({ token: "test-token" }),
}));

import { CoworkerMetricsCard } from "@/components/coworker/CoworkerMetricsCard";
import * as api from "@/lib/api";
import type {
  CoworkerMetricsDay,
  CoworkerMetricsHistory,
  CoworkerMetricsSource,
  CoworkerMetricsTotals,
} from "@/lib/types";

function totals(overrides: Partial<CoworkerMetricsTotals> = {}): CoworkerMetricsTotals {
  return {
    turns: 0,
    pings: 0,
    input_tokens: 0,
    output_tokens: 0,
    cache_read_tokens: 0,
    cache_write_tokens: 0,
    observed_input_tokens: 0,
    cache_read_rate: null,
    ping_input_tokens: 0,
    ping_output_tokens: 0,
    ping_cache_read_tokens: 0,
    ping_cache_write_tokens: 0,
    warm_turns: 0,
    warm_hits: 0,
    ping_failures: 0,
    original_messages: 0,
    sent_messages: 0,
    saved_messages: 0,
    trimmed_messages: 0,
    dropped_messages: 0,
    rewritten_messages: 0,
    system_holds: 0,
    ...overrides,
  };
}

function history(overrides: Partial<CoworkerMetricsHistory> = {}): CoworkerMetricsHistory {
  return {
    days: [],
    total_turns_30d: 0,
    total_pings_30d: 0,
    input_tokens_30d: 0,
    output_tokens_30d: 0,
    cache_read_tokens_30d: 0,
    cache_write_tokens_30d: 0,
    observed_input_tokens_30d: 0,
    cache_read_rate_30d: null,
    ping_input_tokens_30d: 0,
    ping_output_tokens_30d: 0,
    ping_cache_read_tokens_30d: 0,
    ping_cache_write_tokens_30d: 0,
    warm_turns_30d: 0,
    warm_hits_30d: 0,
    ping_failures_30d: 0,
    original_messages_30d: 0,
    sent_messages_30d: 0,
    saved_messages_30d: 0,
    trimmed_messages_30d: 0,
    dropped_messages_30d: 0,
    rewritten_messages_30d: 0,
    system_holds_30d: 0,
    sources_30d: [],
    updated_at: null,
    ...overrides,
  };
}

describe("CoworkerMetricsCard", () => {
  afterEach(() => vi.restoreAllMocks());

  it("shows an empty state before any activity is recorded", async () => {
    vi.spyOn(api, "fetchCoworkerMetrics").mockResolvedValue(history());
    render(<CoworkerMetricsCard />);
    expect(await screen.findByText(/No cache activity/i)).toBeInTheDocument();
  });

  it("renders 30-day KPIs and the source breakdown", async () => {
    const day: CoworkerMetricsDay = {
      date: "2026-10-01",
      ...totals({
        turns: 12,
        pings: 8,
        cache_read_tokens: 40000,
        cache_write_tokens: 5000,
        observed_input_tokens: 50000,
        cache_read_rate: 0.8,
        warm_turns: 8,
        warm_hits: 6,
        ping_failures: 1,
        saved_messages: 21,
        trimmed_messages: 14,
      }),
    };
    const source: CoworkerMetricsSource = {
      source: "user",
      ...totals({
        turns: 12,
        cache_read_tokens: 40000,
        cache_write_tokens: 5000,
        observed_input_tokens: 50000,
        cache_read_rate: 0.8,
      }),
    };
    vi.spyOn(api, "fetchCoworkerMetrics").mockResolvedValue(
      history({
        days: [day],
        sources_30d: [source],
        total_turns_30d: 12,
        total_pings_30d: 8,
        cache_read_tokens_30d: 40000,
        cache_write_tokens_30d: 5000,
        observed_input_tokens_30d: 50000,
        cache_read_rate_30d: 0.8,
        warm_hits_30d: 6,
        ping_failures_30d: 1,
        saved_messages_30d: 21,
        trimmed_messages_30d: 14,
      }),
    );

    render(<CoworkerMetricsCard />);

    expect(await screen.findByText("80%")).toBeInTheDocument();
    expect(screen.getByText("6/8")).toBeInTheDocument();
    expect(screen.getByText("21")).toBeInTheDocument();
    expect(screen.getByText("user")).toBeInTheDocument();
  });
});

import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { CoworkerAdvisorControl } from "@/components/coworker/CoworkerAdvisorControl";
import { CoworkerAdvisorExchanges } from "@/components/coworker/CoworkerAdvisorExchanges";
import {
  CoworkerCacheUsageBlock,
  formatPercent,
  formatTokens,
} from "@/components/coworker/CoworkerCacheUsage";
import { CoworkerHeaderControls } from "@/components/coworker/CoworkerHeaderControls";
import * as api from "@/lib/api";
import type { CoworkerCacheUsage, CoworkerStatus } from "@/lib/types";

const USAGE: CoworkerCacheUsage = {
  calls: 3,
  reported: true,
  hit_rate: 0.45,
  input_tokens: 12_000,
  output_tokens: 300,
  cache_read_tokens: 5400,
  cache_write_tokens: 900,
  last: { at: 1, input_tokens: 4000, cache_read_tokens: 3600, cache_write_tokens: 0, hit_rate: 0.9 },
  recent_hit_rates: [0, 0.9, null],
};

function status(overrides: Partial<CoworkerStatus["advisor"]> = {}, usage?: CoworkerCacheUsage): CoworkerStatus {
  return {
    caching: {
      enabled: true,
      is_warm: false,
      idle_seconds: null,
      ttl_seconds: 300,
      remaining_seconds: 0,
      trimmed_messages: 0,
      wasted_tools: 0,
      dropped_junk: 0,
      rewritten_messages: 0,
      system_frozen: false,
      sent_messages: 0,
      original_messages: 0,
      usage,
    },
    advisor: {
      enabled: false,
      preset: null,
      uses: 0,
      max_uses: 10,
      max_tokens: 4096,
      breaker_open_seconds: 0,
      mode: "coding",
      default_preset: null,
      history: [],
      ...overrides,
    },
    room: { enabled: false, armed: false, agents: [], state_entries: [] },
    coding: { enabled: true, tasks: [] },
    participants: [],
    mentions: [
      { id: "agy", kind: "coding", label: "agy", detail: "coding agent", enabled: true },
    ],
  };
}

const client = { requestMutation: vi.fn() };

afterEach(() => {
  vi.restoreAllMocks();
  client.requestMutation.mockReset();
});

describe("cache usage", () => {
  it("formats tokens and percentages", () => {
    expect(formatTokens(950)).toBe("950");
    expect(formatTokens(5400)).toBe("5.4k");
    expect(formatTokens(48_000)).toBe("48k");
    expect(formatTokens(2_500_000)).toBe("2.5M");
    expect(formatPercent(0.451)).toBe("45%");
    expect(formatPercent(null)).toBe("–");
  });

  it("shows hit rate, read and write tokens", () => {
    render(<CoworkerCacheUsageBlock usage={USAGE} />);
    expect(screen.getByText("45%")).toBeInTheDocument();
    expect(screen.getByText("5.4k")).toBeInTheDocument();
    expect(screen.getByText(/Last request: 90% from cache/)).toBeInTheDocument();
  });

  it("says so when the provider reports no cache figures", () => {
    render(<CoworkerCacheUsageBlock usage={{ ...USAGE, reported: false, hit_rate: null }} />);
    expect(screen.getByText(/does not report prompt-cache usage/)).toBeInTheDocument();
    expect(screen.queryByText("45%")).not.toBeInTheDocument();
  });

  it("renders nothing on servers without the field", () => {
    const { container } = render(<CoworkerCacheUsageBlock usage={undefined} />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe("advisor exchanges", () => {
  it("lists newest first and expands the advice", () => {
    render(
      <CoworkerAdvisorExchanges
        exchanges={[
          { at: 1, model: "m", mode: "brainstorm", focus: "old question", advice: "old advice", n: 1 },
          { at: 2, model: "m", mode: "brainstorm", focus: "new question", advice: "new advice", n: 2 },
        ]}
      />,
    );
    const rows = screen.getAllByRole("button");
    expect(rows[0]).toHaveTextContent("new question");
    expect(screen.getByText("new advice")).toBeInTheDocument(); // newest starts open
    expect(screen.queryByText("old advice")).not.toBeInTheDocument();
    fireEvent.click(rows[1]);
    expect(screen.getByText("old advice")).toBeInTheDocument();
  });

  it("explains the empty state", () => {
    render(<CoworkerAdvisorExchanges exchanges={[]} />);
    expect(screen.getByText(/No consults yet/)).toBeInTheDocument();
  });
});

describe("advisor switch", () => {
  it("turns the advisor on with the chosen preset and adopts the returned status", async () => {
    vi.spyOn(api, "fetchCoworkerSettings").mockResolvedValue({ presets: ["default", "opus"] } as never);
    const setSpy = vi
      .spyOn(api, "setCoworkerAdvisor")
      .mockResolvedValue(status({ enabled: true, preset: "opus", mode: "brainstorm" }));
    const onStatus = vi.fn();

    render(
      <CoworkerAdvisorControl client={client} sessionKey="websocket:s" token="t" status={status()} onStatus={onStatus} />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Advisor" }));
    const toggle = await screen.findByRole("switch");
    await waitFor(() => expect(toggle).toBeEnabled());
    fireEvent.click(toggle);

    await waitFor(() => expect(setSpy).toHaveBeenCalledWith(client, "websocket:s", { enabled: true, preset: "opus" }));
    await waitFor(() => expect(onStatus).toHaveBeenCalledTimes(1));
    expect(onStatus.mock.calls[0][0].advisor.mode).toBe("brainstorm");
  });

  it("switches mode without touching the on/off state", async () => {
    vi.spyOn(api, "fetchCoworkerSettings").mockResolvedValue({ presets: ["default"] } as never);
    const setSpy = vi.spyOn(api, "setCoworkerAdvisor").mockResolvedValue(status({ enabled: true, preset: "opus" }));
    render(
      <CoworkerAdvisorControl
        client={client}
        sessionKey="websocket:s"
        token="t"
        status={status({ enabled: true, preset: "opus" })}
        onStatus={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Advisor" }));
    fireEvent.click(await screen.findByRole("button", { name: "Brainstorm" }));
    await waitFor(() => expect(setSpy).toHaveBeenCalledWith(client, "websocket:s", { mode: "brainstorm" }));
  });

  it("shows the server's refusal instead of failing silently", async () => {
    vi.spyOn(api, "fetchCoworkerSettings").mockResolvedValue({ presets: ["opus"] } as never);
    vi.spyOn(api, "setCoworkerAdvisor").mockRejectedValue(new Error("no advisor preset configured"));
    render(
      <CoworkerAdvisorControl client={client} sessionKey="websocket:s" token="t" status={status()} onStatus={vi.fn()} />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Advisor" }));
    const toggle = await screen.findByRole("switch");
    await waitFor(() => expect(toggle).toBeEnabled());
    fireEvent.click(toggle);
    expect(await screen.findByRole("alert")).toHaveTextContent("no advisor preset configured");
  });

  it("shows cache warning when cache is warm", async () => {
    vi.spyOn(api, "fetchCoworkerSettings").mockResolvedValue({ presets: ["default"] } as never);
    const warmStatus = status({ enabled: true, preset: "opus" });
    warmStatus.caching.is_warm = true;

    render(
      <CoworkerAdvisorControl
        client={client}
        sessionKey="websocket:s"
        token="t"
        status={warmStatus}
        onStatus={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Advisor" }));
    expect(await screen.findByText(/full cache-write price/)).toBeInTheDocument();
  });

  it("resets consults budget when reset button is clicked", async () => {
    vi.spyOn(api, "fetchCoworkerSettings").mockResolvedValue({ presets: ["default"] } as never);
    const setSpy = vi.spyOn(api, "setCoworkerAdvisor").mockResolvedValue(status({ enabled: true, preset: "opus", uses: 0 }));
    render(
      <CoworkerAdvisorControl
        client={client}
        sessionKey="websocket:s"
        token="t"
        status={status({ enabled: true, preset: "opus", uses: 3, max_uses: 10 })}
        onStatus={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Advisor" }));
    const resetBtn = await screen.findByTestId("advisor-reset-uses-btn");
    expect(resetBtn).toBeEnabled();
    fireEvent.click(resetBtn);
    await waitFor(() => expect(setSpy).toHaveBeenCalledWith(client, "websocket:s", { reset_uses: true }));
  });
});

describe("header controls", () => {
  it("reports the mentionable agents to the composer", async () => {
    vi.spyOn(api, "fetchCoworkerStatus").mockResolvedValue(status());
    const onMentionsChange = vi.fn();
    render(
      <CoworkerHeaderControls
        client={client}
        sessionKey="websocket:s"
        token="t"
        onMentionsChange={onMentionsChange}
      />,
    );
    await act(async () => {
      await Promise.resolve();
    });
    await waitFor(() =>
      expect(onMentionsChange).toHaveBeenCalledWith([
        { id: "agy", kind: "coding", label: "agy", detail: "coding agent", enabled: true },
      ]),
    );
  });

  it("shows the session hit rate next to the inspector icon", async () => {
    vi.spyOn(api, "fetchCoworkerStatus").mockResolvedValue(status({}, USAGE));
    render(<CoworkerHeaderControls client={client} sessionKey="websocket:s" token="t" />);
    expect(await screen.findByTestId("coworker-cache-hit-rate")).toHaveTextContent("45%");
  });
});

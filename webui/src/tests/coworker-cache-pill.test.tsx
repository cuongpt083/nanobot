import { act, fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { CoworkerCachePill } from "@/components/coworker/CoworkerCachePill";
import * as api from "@/lib/api";
import type { CoworkerKeepaliveStatus, CoworkerStatus } from "@/lib/types";

function makeKeepalive(overrides: Partial<CoworkerKeepaliveStatus> = {}): CoworkerKeepaliveStatus {
  return {
    known: true,
    enabled: true,
    source: "session",
    strategy: "ping",
    effective_strategy: "ping",
    window_min: 30,
    provider: "anthropic",
    model: "claude-3-5-sonnet",
    guaranteed: true,
    real_turn_at: 1000,
    last_touch_at: 1000,
    ttl_s: 300,
    expires_at: 1000 + 300,
    ttl1h_supported: true,
    ttl1h_armed: false,
    pings: 1,
    ping_cap: 6,
    can_ping: true,
    next_ping_at: 1240,
    est_tokens_per_ping: 500,
    spent: { pings: 1, input: 500, cache_read: 400 },
    parked: false,
    last_error: "",
    run_active: false,
    ...overrides,
  };
}

function makeStatus(keepalive?: CoworkerKeepaliveStatus): CoworkerStatus {
  return {
    caching: {
      enabled: true,
      is_warm: Boolean(keepalive?.expires_at && keepalive.expires_at > Date.now() / 1000),
      idle_seconds: 10,
      ttl_seconds: 300,
      remaining_seconds: 290,
      trimmed_messages: 0,
      wasted_tools: 0,
      dropped_junk: 0,
      rewritten_messages: 0,
      system_frozen: false,
      sent_messages: 1,
      original_messages: 1,
      keepalive,
    },
    advisor: {
      enabled: false,
      preset: null,
      uses: 0,
      max_uses: 10,
      max_tokens: 4096,
      breaker_open_seconds: 0,
    },
    room: { enabled: false, armed: false, agents: [], state_entries: [] },
    coding: { enabled: false, tasks: [] },
  };
}

describe("CoworkerCachePill", () => {
  const dummyClient = {} as api.WebUIMutationTransport;

  it("hides when keepalive is unknown", () => {
    const status = makeStatus(makeKeepalive({ known: false }));
    const { container } = render(
      <CoworkerCachePill
        client={dummyClient}
        sessionKey="s1"
        token="tok"
        status={status}
        onStatus={vi.fn()}
      />
    );
    expect(container.firstChild).toBeNull();
  });

  it("renders warm countdown with flame when warm and keepalive is enabled", () => {
    const future = Date.now() / 1000 + 200;
    const status = makeStatus(makeKeepalive({ expires_at: future, enabled: true }));
    render(
      <CoworkerCachePill
        client={dummyClient}
        sessionKey="s1"
        token="tok"
        status={status}
        onStatus={vi.fn()}
      />
    );
    expect(screen.getByRole("button")).toHaveTextContent("🔥");
  });

  it("renders cold indicator when cache is cold", () => {
    const past = Date.now() / 1000 - 100;
    const status = makeStatus(makeKeepalive({ expires_at: past, enabled: true }));
    render(
      <CoworkerCachePill
        client={dummyClient}
        sessionKey="s1"
        token="tok"
        status={status}
        onStatus={vi.fn()}
      />
    );
    expect(screen.getByRole("button")).toHaveTextContent("❄️");
  });

  it("renders running state when run is active", () => {
    const status = makeStatus(makeKeepalive({ run_active: true }));
    render(
      <CoworkerCachePill
        client={dummyClient}
        sessionKey="s1"
        token="tok"
        status={status}
        onStatus={vi.fn()}
      />
    );
    expect(screen.getByRole("button")).toHaveTextContent(/running|chạy/i);
  });

  it("opens popover and triggers setCoworkerKeepalive when toggling mode", async () => {
    const spy = vi.spyOn(api, "setCoworkerKeepalive").mockResolvedValue(makeStatus());
    const onStatus = vi.fn();
    const future = Date.now() / 1000 + 200;
    const status = makeStatus(makeKeepalive({ expires_at: future, enabled: true, source: "session" }));

    render(
      <CoworkerCachePill
        client={dummyClient}
        sessionKey="s1"
        token="tok"
        status={status}
        onStatus={onStatus}
      />
    );

    // Click pill to open popover
    fireEvent.click(screen.getByRole("button"));

    // Find "Tắt" / Off button in the segmented control
    const offButton = screen.getByRole("button", { name: /Off|Tắt/i });
    await act(async () => {
      fireEvent.click(offButton);
    });

    expect(spy).toHaveBeenCalledWith(dummyClient, "s1", { enabled: false });
  });

  it("renders auto-optimize section with pending indicator and saved messages count", () => {
    const future = Date.now() / 1000 + 200;
    const baseStatus = makeStatus(makeKeepalive({ expires_at: future }));
    baseStatus.caching.optimize = {
      enabled: true,
      latched: false,
      pending: true,
      source: "session",
      dropped: 2,
      rewritten: 1,
      trimmed: 4,
      saved_messages: 5,
    };

    render(
      <CoworkerCachePill
        client={dummyClient}
        sessionKey="s1"
        token="tok"
        status={baseStatus}
        onStatus={vi.fn()}
      />
    );

    // Open popover
    fireEvent.click(screen.getByRole("button"));

    // Check pending notice and saved messages
    expect(screen.getByText(/Will apply when cache cools down|Sẽ áp dụng khi cache nguội/i)).toBeInTheDocument();
    expect(screen.getByText(/Trimmed 5 messages|Đã rút gọn 5 tin nhắn/i)).toBeInTheDocument();
  });
});

import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

import { CoworkerInspectorPopover } from "@/components/coworker/CoworkerInspectorPopover";
import * as api from "@/lib/api";

describe("CoworkerInspectorPopover", () => {
  it("renders trigger button", () => {
    vi.spyOn(api, "fetchCoworkerStatus").mockResolvedValue({
      caching: {
        enabled: true,
        is_warm: true,
        idle_seconds: 45,
        ttl_seconds: 300,
        remaining_seconds: 255,
        trimmed_messages: 2,
        wasted_tools: 1,
        dropped_junk: 4,
        rewritten_messages: 1,
        system_frozen: true,
        sent_messages: 10,
        original_messages: 15,
      },
      advisor: {
        enabled: true,
        preset: "claude-3-7-sonnet",
        uses: 2,
        max_uses: 5,
        max_tokens: 4000,
        breaker_open_seconds: 0,
      },
      room: {
        enabled: true,
        armed: true,
        agents: ["reviewer", "coder"],
        state_entries: [{ key: "task", preview: "Build API" }],
      },
      coding: {
        enabled: true,
        tasks: [],
      },
    });

    render(
      <CoworkerInspectorPopover
        sessionKey="websocket:test-key"
        token="test-token"
      />,
    );

    const button = screen.getByRole("button", { name: /Coworker Inspector/i });
    expect(button).toBeInTheDocument();
  });
});

import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

import { CoworkerInspectorPopover } from "@/components/coworker/CoworkerInspectorPopover";
import * as api from "@/lib/api";
import type { CoworkerStatus } from "@/lib/types";

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

  it("marks in-place coding tasks and keeps worktree tasks unmarked", () => {
    const task = (id: string, mode: "worktree" | "direct") => ({
      id,
      backend: "pi",
      status: "succeeded",
      brief: `brief ${id}`,
      branch: mode === "direct" ? "" : `coworker/code/${id}`,
      mode,
      diffstat: mode === "direct" ? "1 added, 0 modified, 0 deleted" : "1 file changed",
      created_at: 1,
      updated_at: 2,
    });
    const status = {
      caching: {
        enabled: false,
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
      },
      advisor: { enabled: false, preset: null, uses: 0, max_uses: 5, max_tokens: 4000 },
      room: { enabled: false, armed: false, agents: [], state_entries: [] },
      coding: { enabled: true, tasks: [task("ct-doc", "direct"), task("ct-git", "worktree")] },
    } as unknown as CoworkerStatus;

    render(
      <CoworkerInspectorPopover
        sessionKey="websocket:test-key"
        token="test-token"
        open
        feed={{ status, loading: false, liveRemainingSeconds: 0 }}
      />,
    );

    expect(screen.getByText("ct-doc")).toBeInTheDocument();
    expect(screen.getByText("ct-git")).toBeInTheDocument();
    const badges = screen.getAllByTestId("task-mode");
    expect(badges).toHaveLength(1);
    expect(badges[0]).toHaveTextContent("In place");
    expect(badges[0].parentElement).toHaveTextContent("ct-doc");
    expect(screen.getByText("1 added, 0 modified, 0 deleted")).toBeInTheDocument();
  });
});

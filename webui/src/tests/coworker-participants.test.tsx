import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { CoworkerHeaderControls } from "@/components/coworker/CoworkerHeaderControls";
import {
  CoworkerParticipantList,
  CoworkerParticipantsStrip,
  formatElapsed,
  visibleParticipants,
} from "@/components/coworker/CoworkerParticipants";
import { parseCodingMeta, parseCoworkerMessage } from "@/components/coworker/CoworkerMessageCard";
import * as api from "@/lib/api";
import type { CoworkerParticipant, CoworkerStatus } from "@/lib/types";

function participant(overrides: Partial<CoworkerParticipant>): CoworkerParticipant {
  return {
    id: "p",
    kind: "teammate",
    label: "Teammate",
    engine: "preset:default",
    state: "idle",
    task: null,
    since: null,
    detail: {},
    ...overrides,
  };
}

function status(participants: CoworkerParticipant[]): CoworkerStatus {
  return {
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
    advisor: {
      enabled: true,
      preset: "strong",
      uses: 1,
      max_uses: 10,
      max_tokens: 4096,
      breaker_open_seconds: 0,
    },
    room: { enabled: true, armed: true, agents: [], state_entries: [] },
    coding: { enabled: true, tasks: [] },
    participants,
  };
}

describe("participants helpers", () => {
  it("hides idle participants", () => {
    const shown = visibleParticipants([
      participant({ id: "a", state: "idle" }),
      participant({ id: "b", state: "working" }),
      participant({ id: "c", state: "done" }),
    ]);
    expect(shown.map((p) => p.id)).toEqual(["b", "c"]);
    expect(visibleParticipants(undefined)).toEqual([]);
  });

  it("formats elapsed time", () => {
    const now = 1_000_000_000_000;
    expect(formatElapsed(null, now)).toBe("");
    expect(formatElapsed(now / 1000 - 12, now)).toBe("12s");
    expect(formatElapsed(now / 1000 - 125, now)).toBe("2m");
    expect(formatElapsed(now / 1000 - 3 * 3600 - 5 * 60, now)).toBe("3h05m");
  });

  it("extracts backend, status and line counts from a coding result", () => {
    const raw =
      "Task `ct-1` (agy) finished with status: `failed_acceptance`\n" +
      "**Diffstat**:\n```\n a.py | 3 +++\n 2 files changed, 12 insertions(+), 4 deletions(-)\n```";
    expect(parseCodingMeta(raw)).toEqual({
      backend: "agy",
      status: "failed_acceptance",
      added: 12,
      removed: 4,
    });
    expect(parseCodingMeta("nothing useful")).toEqual({});
    expect(parseCoworkerMessage(`[auto-coding-result] ${raw}`)?.coding?.backend).toBe("agy");
  });
});

describe("CoworkerParticipantsStrip", () => {
  it("renders nothing when everyone is idle", () => {
    const { container } = render(
      <CoworkerParticipantsStrip participants={[participant({ state: "idle" })]} />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("renders a chip per active participant and reports clicks", () => {
    const onSelect = vi.fn();
    render(
      <CoworkerParticipantsStrip
        participants={[
          participant({ id: "researcher", label: "🔎 Researcher", state: "working", task: "find facts" }),
          participant({ id: "advisor", kind: "advisor", label: "Advisor", state: "paused" }),
          participant({ id: "writer", label: "Writer", state: "idle" }),
        ]}
        onSelect={onSelect}
      />,
    );
    const chips = screen.getAllByRole("button");
    expect(chips).toHaveLength(2);
    expect(chips[0]).toHaveAttribute("data-state", "working");
    expect(chips[0]).toHaveAttribute("title", expect.stringContaining("find facts"));
    fireEvent.click(chips[0]);
    expect(onSelect).toHaveBeenCalledWith(expect.objectContaining({ id: "researcher" }));
  });
});

describe("CoworkerParticipantList", () => {
  it("shows an empty message without participants", () => {
    render(<CoworkerParticipantList participants={[]} />);
    expect(screen.getByText(/No other agents are involved yet/i)).toBeInTheDocument();
  });

  it("shows coding progress and the advisor's last consult", () => {
    render(
      <CoworkerParticipantList
        participants={[
          participant({
            id: "ct-1",
            kind: "coding",
            label: "pi · ct-1",
            engine: "backend:pi",
            state: "working",
            task: "add a flag",
            since: Date.now() / 1000 - 90,
            detail: { tools: 7, last_tool: "run_command", rounds: 2 },
          }),
          participant({
            id: "advisor",
            kind: "advisor",
            label: "Advisor",
            engine: "preset:strong",
            state: "idle",
            detail: {
              uses: 3,
              max_uses: 10,
              last_consult: { at: 1, model: "strong", focus: "review the diff", duration_ms: 4200, ok: true },
            },
          }),
        ]}
      />,
    );
    expect(screen.getByText("7 tools")).toBeInTheDocument();
    expect(screen.getByText("run_command")).toBeInTheDocument();
    expect(screen.getByText("round 2")).toBeInTheDocument();
    expect(screen.getByText("3/10 consults")).toBeInTheDocument();
    expect(screen.getByText(/review the diff/)).toBeInTheDocument();
  });
});

describe("CoworkerHeaderControls polling", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("keeps polling while participants are live and stops once they settle", async () => {
    const fetchSpy = vi
      .spyOn(api, "fetchCoworkerStatus")
      .mockResolvedValueOnce(status([participant({ id: "researcher", label: "Researcher", state: "working" })]))
      .mockResolvedValueOnce(status([participant({ id: "researcher", label: "Researcher", state: "working" })]))
      .mockResolvedValue(status([participant({ id: "researcher", label: "Researcher", state: "done" })]));

    render(<CoworkerHeaderControls sessionKey="websocket:s" token="t" />);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(fetchSpy).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("button", { name: /Researcher/ })).toHaveAttribute("data-state", "working");

    await act(async () => {
      await vi.advanceTimersByTimeAsync(3100);
    });
    expect(fetchSpy).toHaveBeenCalledTimes(2);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(3100);
    });
    expect(screen.getByRole("button", { name: /Researcher/ })).toHaveAttribute("data-state", "done");
    const settledCalls = fetchSpy.mock.calls.length;
    expect(settledCalls).toBe(3);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(30_000);
    });
    expect(fetchSpy).toHaveBeenCalledTimes(settledCalls); // idle chat costs nothing
  });

  it("does not poll an idle session beyond the initial probe", async () => {
    const fetchSpy = vi.spyOn(api, "fetchCoworkerStatus").mockResolvedValue(status([]));
    render(<CoworkerHeaderControls sessionKey="websocket:s" token="t" />);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(20_000);
    });
    expect(fetchSpy).toHaveBeenCalledTimes(1);
  });
});

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { CoworkerDirectConfirm } from "@/components/coworker/CoworkerDirectConfirm";
import * as api from "@/lib/api";
import type { CoworkerCodingProject, CoworkerStatus } from "@/lib/types";

function makeStatus(project?: Partial<CoworkerCodingProject>): CoworkerStatus {
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
      enabled: false,
      preset: null,
      uses: 0,
      max_uses: 10,
      max_tokens: 4096,
    } as CoworkerStatus["advisor"],
    room: { enabled: false, armed: false, agents: [] } as unknown as CoworkerStatus["room"],
    coding: {
      enabled: true,
      tasks: [],
      project: {
        path: "/work/slides",
        non_git: "ask",
        direct_allowed: false,
        pending_direct: "/work/slides",
        ...project,
      },
    },
  } as CoworkerStatus;
}

const client = {} as api.WebUIMutationTransport;

function renderConfirm(status: CoworkerStatus | null, onStatus = vi.fn()) {
  render(
    <CoworkerDirectConfirm
      client={client}
      sessionKey="websocket:abc"
      status={status}
      onStatus={onStatus}
    />,
  );
  return onStatus;
}

describe("CoworkerDirectConfirm", () => {
  it("stays hidden until the backend raises a pending request", () => {
    renderConfirm(makeStatus({ pending_direct: null }));
    expect(screen.queryByTestId("direct-confirm")).not.toBeInTheDocument();
    renderConfirm(null);
    expect(screen.queryByTestId("direct-confirm")).not.toBeInTheDocument();
  });

  it("shows the folder and warns about the missing workspace restriction", () => {
    renderConfirm(makeStatus());
    expect(screen.getByTestId("direct-confirm")).toBeInTheDocument();
    expect(screen.getByText("/work/slides")).toBeInTheDocument();
    expect(screen.getByText(/not a git repository/)).toBeInTheDocument();
    expect(screen.getByText(/not limited by this chat's workspace restriction/)).toBeInTheDocument();
  });

  it("allows editing in place for exactly this chat's project", async () => {
    const next = makeStatus({ pending_direct: null, direct_allowed: true });
    const spy = vi.spyOn(api, "setCoworkerCoding").mockResolvedValue(next);
    const onStatus = renderConfirm(makeStatus());
    fireEvent.click(screen.getByTestId("direct-confirm-allow"));
    await waitFor(() => expect(onStatus).toHaveBeenCalledWith(next));
    expect(spy).toHaveBeenCalledWith(client, "websocket:abc", {
      direct_ok: true,
      path: "/work/slides",
    });
  });

  it("'Not now' answers no and does not grant anything", async () => {
    const spy = vi.spyOn(api, "setCoworkerCoding").mockResolvedValue(makeStatus({ pending_direct: null }));
    renderConfirm(makeStatus());
    fireEvent.click(screen.getByRole("button", { name: "Not now" }));
    await waitFor(() => expect(spy).toHaveBeenCalled());
    expect(spy.mock.calls[0][2]).toEqual({ direct_ok: false, path: "/work/slides" });
  });

  it("shows the error and keeps the question open when the request fails", async () => {
    vi.spyOn(api, "setCoworkerCoding").mockRejectedValue(new Error("path must be this chat's project directory"));
    const onStatus = renderConfirm(makeStatus());
    fireEvent.click(screen.getByTestId("direct-confirm-allow"));
    expect(await screen.findByRole("alert")).toHaveTextContent(/project directory/);
    expect(onStatus).not.toHaveBeenCalled();
    expect(screen.getByTestId("direct-confirm")).toBeInTheDocument();
  });
});

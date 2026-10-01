import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { CoworkerDirectConfirm } from "@/components/coworker/CoworkerDirectConfirm";
import * as api from "@/lib/api";
import type { CoworkerCodingProject, CoworkerInitPreview, CoworkerStatus } from "@/lib/types";

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


function previewFor(overrides: Partial<CoworkerInitPreview> = {}): CoworkerInitPreview {
  return {
    path: "/work/slides",
    digest: "abc123",
    file_count: 2,
    files: ["deck.pptx", "notes.md"],
    total_mb: 1.5,
    gitignore: "node_modules/\n.env\n",
    extra_excludes: [],
    skipped_sensitive: [".env"],
    skipped_large: ["video.mov"],
    skipped_embedded: [],
    existing_repo: false,
    ...overrides,
  };
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

  it("offers to initialise git instead and asks the backend for a preview", async () => {
    const next = makeStatus({ init_preview: previewFor() });
    const spy = vi.spyOn(api, "setCoworkerCoding").mockResolvedValue(next);
    const onStatus = renderConfirm(makeStatus());
    fireEvent.click(screen.getByTestId("direct-confirm-init"));
    await waitFor(() => expect(onStatus).toHaveBeenCalledWith(next));
    expect(spy).toHaveBeenCalledWith(client, "websocket:abc", { init: "preview", path: "/work/slides" });
  });

  it("shows exactly what would be committed before anything is created", () => {
    renderConfirm(makeStatus({ init_preview: previewFor() }));
    expect(screen.getByText("Create a git repository?")).toBeInTheDocument();
    const files = screen.getByTestId("init-files");
    expect(within(files).getByText("deck.pptx")).toBeInTheDocument();
    expect(within(files).getByText("notes.md")).toBeInTheDocument();
    expect(screen.getByText(/2 file\(s\), about 1.5 MB/)).toBeInTheDocument();
    expect(screen.getByText(".env")).toBeInTheDocument(); // left out as a likely secret
    expect(screen.getByText(/Left out \(over 20 MB\)/)).toBeInTheDocument();
    expect(screen.getByText("A new .gitignore will be created")).toBeInTheDocument();
    expect(screen.getByTestId("init-gitignore")).toHaveTextContent("node_modules/");
    expect(screen.queryByTestId("direct-confirm-allow")).not.toBeInTheDocument();
  });

  it("says when an existing .gitignore is kept and when the list is long", () => {
    renderConfirm(
      makeStatus({
        init_preview: previewFor({ gitignore: null, file_count: 250, files: ["a.md", "b.md"] }),
      }),
    );
    expect(screen.getByText("Your existing .gitignore is kept.")).toBeInTheDocument();
    expect(screen.queryByTestId("init-gitignore")).not.toBeInTheDocument();
    expect(screen.getByText(/and 248 more/)).toBeInTheDocument();
  });

  it("confirms the reviewed list, and 'Back' drops the preview without creating anything", async () => {
    const spy = vi.spyOn(api, "setCoworkerCoding").mockResolvedValue(makeStatus({ pending_direct: null }));
    renderConfirm(makeStatus({ init_preview: previewFor() }));
    fireEvent.click(screen.getByTestId("init-confirm"));
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(1));
    expect(spy.mock.calls[0][2]).toEqual({ init: "confirm", path: "/work/slides" });

    fireEvent.click(screen.getByRole("button", { name: "Back" }));
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(2));
    expect(spy.mock.calls[1][2]).toEqual({ init: "cancel", path: "/work/slides" });
  });

  it("shows the backend's refusal and keeps the review open", async () => {
    vi.spyOn(api, "setCoworkerCoding").mockRejectedValue(
      new Error("The folder changed since the preview. Review the new list and confirm again."),
    );
    renderConfirm(makeStatus({ init_preview: previewFor() }));
    fireEvent.click(screen.getByTestId("init-confirm"));
    expect(await screen.findByRole("alert")).toHaveTextContent(/changed since the preview/);
    expect(screen.getByTestId("init-review")).toBeInTheDocument();
  });

  it("stays open on the review even after the pending request was cleared", () => {
    renderConfirm(makeStatus({ pending_direct: null, init_preview: previewFor() }));
    expect(screen.getByTestId("init-review")).toBeInTheDocument();
  });
});

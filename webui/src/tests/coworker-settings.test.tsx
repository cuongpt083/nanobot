import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  CoworkerSettingsEntry,
  dirtySections,
  splitCommand,
  splitLines,
} from "@/components/settings/capabilities/CoworkerSettings";
import { CodingAgentsPanel } from "@/components/settings/system/CodingAgentsPanel";
import * as api from "@/lib/api";
import type { CoworkerSettingsPayload } from "@/lib/types";

const requestMutation = vi.fn();
vi.mock("@/providers/ClientProvider", () => ({
  useClient: () => ({ client: { requestMutation }, token: "test-token" }),
}));

function payload(overrides: Partial<CoworkerSettingsPayload> = {}): CoworkerSettingsPayload {
  return {
    path: "/home/me/.nanobot/coworker.json",
    presets: ["default", "fast", "strong"],
    detection: {
      pi: { name: "pi", command: ["pi"], found: true, path: "/usr/bin/pi", version: "pi 0.84.2", custom: false },
      agy: { name: "agy", command: ["agy"], found: false, path: null, version: null, custom: false },
    },
    repos: [{ path: "/work/app", ok: true, error: null, branch: "main" }],
    config: {
      advisor: {
        preset: "strong",
        max_uses: 10,
        max_tokens: 4096,
        timeout_seconds: 180,
        review_nudge: true,
        first_consult_gap: 2,
        reconsult_gap: 12,
      },
      room: { agents: [], max_chained_turns: 16, guest_timeout_seconds: 900 },
      coding: {
        enabled: true,
        default_backend: "pi",
        pi: {
          command: ["pi"],
          agent_dir: null,
          tools: null,
          extensions: true,
          trust_project_files: false,
          pass_env: [],
          allow_unsandboxed: false,
        },
        agy: {
          command: ["agy"],
          agy_sandbox: true,
          mode: null,
          extra_args: [],
          pass_env: [],
          allow_unsandboxed: false,
        },
        repos: [{ path: "/work/app", acceptance: "pytest -q", base_ref: "main", backend: null }],
        worktree_root: null,
        sandbox: "none",
        timeout_minutes: 45,
        idle_timeout_minutes: 10,
        max_concurrent_per_session: 1,
        max_concurrent_total: 2,
        fix_rounds: 1,
        progress_every_seconds: 60,
        merge_strategy: "squash",
        delete_branch_after_merge: true,
        keep_failed_worktrees_days: 3,
      },
      context: {
        trim: { enabled: false, max_turns: 10 },
        optimize: false,
        freeze_system_prompt: false,
        freeze_max_hold_minutes: 60,
        cache_ttl_seconds: null,
        keepalive: {
          enabled: true,
          strategy: "ping",
          window_minutes: 30,
          max_pings: 4,
          lead_seconds: 60,
        },
      },
    },
    ...overrides,
  };
}

async function openDialog() {
  render(<CoworkerSettingsEntry />);
  fireEvent.click(screen.getByRole("button", { name: /configure/i }));
  await screen.findByRole("tablist").catch(() => null);
  await screen.findByText("/home/me/.nanobot/coworker.json");
}

describe("coworker settings helpers", () => {
  it("splits multi-line and command text", () => {
    expect(splitLines("a\n\n  b  \n")).toEqual(["a", "b"]);
    expect(splitCommand("  pi   --flag ")).toEqual(["pi", "--flag"]);
    expect(splitCommand("")).toEqual([]);
  });

  it("reports which sections differ from the saved config", () => {
    const saved = payload().config;
    const draft = structuredClone(saved);
    expect(dirtySections(draft, saved).size).toBe(0);
    draft.room.agents.push({ id: "a", name: "", emoji: "", bio: "", preset: null, backend: null, instructions: "" });
    draft.advisor.max_uses = 3;
    draft.context.optimize = true;
    expect([...dirtySections(draft, saved)].sort()).toEqual(["advisor", "context", "room"]);
    expect(dirtySections(null, saved).size).toBe(0);
  });
});

describe("CoworkerSettingsEntry", () => {
  beforeEach(() => {
    requestMutation.mockReset();
    vi.restoreAllMocks();
  });

  it("loads settings lazily, edits the advisor and saves only that section", async () => {
    const fetchSpy = vi.spyOn(api, "fetchCoworkerSettings").mockResolvedValue(payload());
    const saved = payload();
    saved.config.advisor.max_uses = 5;
    const updateSpy = vi.spyOn(api, "updateCoworkerSettings").mockResolvedValue(saved);

    render(<CoworkerSettingsEntry />);
    expect(fetchSpy).not.toHaveBeenCalled(); // nothing loads until the dialog opens
    fireEvent.click(screen.getByRole("button", { name: /configure/i }));
    await screen.findByText("/home/me/.nanobot/coworker.json");

    const save = screen.getByRole("button", { name: "Save" });
    expect(save).toBeDisabled();
    fireEvent.change(screen.getAllByRole("spinbutton")[0], { target: { value: "5" } });
    expect(save).toBeEnabled();
    fireEvent.click(save);

    await waitFor(() => expect(updateSpy).toHaveBeenCalledTimes(1));
    const [, sections] = updateSpy.mock.calls[0];
    expect(Object.keys(sections)).toEqual(["advisor"]);
    expect(sections.advisor?.max_uses).toBe(5);
    expect(sections.advisor?.preset).toBe("strong");
    await screen.findByText(/Saved/);
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
  });

  it("shows the server's validation error and keeps the draft", async () => {
    vi.spyOn(api, "fetchCoworkerSettings").mockResolvedValue(payload());
    vi.spyOn(api, "updateCoworkerSettings").mockRejectedValue(
      new api.ApiError(400, "advisor.preset: unknown model preset 'nope'"),
    );
    await openDialog();
    fireEvent.change(screen.getAllByRole("spinbutton")[0], { target: { value: "7" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("unknown model preset");
    expect(screen.getByRole("button", { name: "Save" })).toBeEnabled();
  });

  it("offers a retry when loading fails", async () => {
    const fetchSpy = vi
      .spyOn(api, "fetchCoworkerSettings")
      .mockRejectedValueOnce(new api.ApiError(500, "boom"))
      .mockResolvedValue(payload());
    render(<CoworkerSettingsEntry />);
    fireEvent.click(screen.getByRole("button", { name: /configure/i }));
    expect(await screen.findByText("boom")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await screen.findByText("/home/me/.nanobot/coworker.json");
    expect(fetchSpy).toHaveBeenCalledTimes(2);
  });

  it("adds a teammate and marks the Team tab as unsaved", async () => {
    vi.spyOn(api, "fetchCoworkerSettings").mockResolvedValue(payload());
    await openDialog();
    fireEvent.click(screen.getByRole("button", { name: /^Team/ }));
    fireEvent.click(await screen.findByRole("button", { name: /Add teammate/ }));
    fireEvent.change(screen.getByLabelText("Agent id"), { target: { value: "Researcher" } });
    expect((screen.getByLabelText("Agent id") as HTMLInputElement).value).toBe("researcher");
    expect(screen.getByRole("button", { name: /^Team •/ })).toBeInTheDocument();
  });

  it("requires explicit confirmation before allowing unsandboxed runs", async () => {
    vi.spyOn(api, "fetchCoworkerSettings").mockResolvedValue(payload());
    const updateSpy = vi.spyOn(api, "updateCoworkerSettings").mockResolvedValue(payload());
    await openDialog();
    fireEvent.click(screen.getByRole("button", { name: /^Coding/ }));
    const toggles = await screen.findAllByRole("switch", { name: /run without an OS sandbox/ });
    fireEvent.click(toggles[0]);
    expect(await screen.findByRole("alert")).toHaveTextContent(/read and change anything/);
    expect(toggles[0]).not.toBeChecked(); // still off until confirmed
    fireEvent.click(screen.getByRole("button", { name: /I understand, enable/ }));
    await waitFor(() => expect(screen.getAllByRole("switch", { name: /run without an OS sandbox/ })[0]).toBeChecked());
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(updateSpy).toHaveBeenCalled());
    expect(updateSpy.mock.calls[0][1].coding?.pi.allow_unsandboxed).toBe(true);
  });

  it("switches to the Cache tab and edits keep-warm settings", async () => {
    vi.spyOn(api, "fetchCoworkerSettings").mockResolvedValue(payload());
    const updateSpy = vi.spyOn(api, "updateCoworkerSettings").mockResolvedValue(payload());
    await openDialog();
    fireEvent.click(screen.getByRole("button", { name: /^Cache/ }));
    expect(await screen.findByText(/Prompt Cache Keep-Warm|Giữ ấm Prompt Cache/i)).toBeInTheDocument();
    expect(screen.getByText(/Keep-alive pings replay/i)).toBeInTheDocument();

    // Toggle keep-warm off
    const toggles = screen.getAllByRole("switch");
    fireEvent.click(toggles[0]);

    // Save button should be active and save context section
    const saveBtn = screen.getByRole("button", { name: "Save" });
    expect(saveBtn).toBeEnabled();
    fireEvent.click(saveBtn);
    await waitFor(() => expect(updateSpy).toHaveBeenCalled());
    expect(updateSpy.mock.calls[0][1].context?.keepalive.enabled).toBe(false);
  });

  it("edits discussion gate and min chars in Advisor tab", async () => {
    vi.spyOn(api, "fetchCoworkerSettings").mockResolvedValue(payload());
    const updateSpy = vi.spyOn(api, "updateCoworkerSettings").mockResolvedValue(payload());
    await openDialog();
    expect(await screen.findByText(/Discussion gate/i)).toBeInTheDocument();

    const selects = screen.getAllByRole("combobox");
    const gateSelect = selects.find((s) => (s as HTMLSelectElement).value === "brainstorm") || selects[1];
    fireEvent.change(gateSelect, { target: { value: "always" } });

    const saveBtn = screen.getByRole("button", { name: "Save" });
    expect(saveBtn).toBeEnabled();
    fireEvent.click(saveBtn);
    await waitFor(() => expect(updateSpy).toHaveBeenCalled());
    expect(updateSpy.mock.calls[0][1].advisor?.discussion_gate).toBe("always");
  });
});

describe("CodingAgentsPanel", () => {
  beforeEach(() => vi.restoreAllMocks());

  it("shows Pi and agy detection and links to the Coworker settings", async () => {
    vi.spyOn(api, "fetchCoworkerSettings").mockResolvedValue(payload());
    const onConfigure = vi.fn();
    render(<CodingAgentsPanel onConfigure={onConfigure} />);
    const pi = await screen.findByText("Pi", { selector: "h3" });
    expect(pi.closest("article")).toHaveTextContent("pi 0.84.2");
    expect(pi.closest("article")).toHaveTextContent("/usr/bin/pi");
    expect(pi.closest("article")).toHaveTextContent("Default backend");
    const agy = screen.getByText("agy (Antigravity CLI)").closest("article");
    expect(agy).toHaveTextContent("not found");
    fireEvent.click(screen.getByRole("button", { name: /Configure in Coworker settings/ }));
    expect(onConfigure).toHaveBeenCalledTimes(1);
  });

  it("surfaces a load failure", async () => {
    vi.spyOn(api, "fetchCoworkerSettings").mockRejectedValue(new Error("gateway down"));
    render(<CodingAgentsPanel />);
    expect(await screen.findByRole("alert")).toHaveTextContent("gateway down");
  });
});

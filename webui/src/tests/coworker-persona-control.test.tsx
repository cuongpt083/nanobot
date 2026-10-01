import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

import { CoworkerPersonaControl } from "@/components/coworker/CoworkerPersonaControl";
import * as api from "@/lib/api";
import type { CoworkerStatus } from "@/lib/types";

function mockStatus(overrides?: Partial<CoworkerStatus>): CoworkerStatus {
  return {
    caching: {
      is_warm: false,
      hit_rate: 0,
      read_tokens: 0,
      written_tokens: 0,
      input_tokens: 0,
      last_request: null,
      recent_requests: [],
    },
    advisor: {
      enabled: false,
      preset: null,
      default_preset: null,
      mode: "coding",
      uses: 0,
      max_uses: 10,
    },
    room: {
      enabled: true,
      armed: false,
      agents: ["researcher", "writer"],
      state_entries: 0,
    },
    coding: {
      enabled: false,
      tasks: [],
    },
    persona: null,
    personas: [
      {
        id: "researcher",
        name: "Deep Researcher",
        emoji: "🔎",
        bio: "Fact checking",
        preset: "sonnet",
      },
      {
        id: "writer",
        name: "Marketing Writer",
        emoji: "✍️",
        bio: "Creative copy",
        preset: null,
      },
    ],
    ...overrides,
  };
}

describe("CoworkerPersonaControl", () => {
  const client: api.WebUIMutationTransport = {
    sendMutation: vi.fn(),
  };

  it("does not render if no personas available and none active", () => {
    const status = mockStatus({ personas: [], persona: null });
    const { container } = render(
      <CoworkerPersonaControl
        client={client}
        sessionKey="s1"
        token="tok"
        status={status}
        onStatus={vi.fn()}
      />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("renders trigger button and opens popover listing personas", async () => {
    const status = mockStatus();
    render(
      <CoworkerPersonaControl
        client={client}
        sessionKey="s1"
        token="tok"
        status={status}
        onStatus={vi.fn()}
      />,
    );

    const btn = screen.getByTestId("persona-control-btn");
    expect(btn).toBeInTheDocument();
    expect(btn).toHaveTextContent("Persona");

    fireEvent.click(btn);
    expect(await screen.findByText("Session Persona")).toBeInTheDocument();
    expect(screen.getByText("Deep Researcher")).toBeInTheDocument();
    expect(screen.getByText("Marketing Writer")).toBeInTheDocument();
    expect(screen.getByText("Default Coordinator")).toBeInTheDocument();
  });

  it("selects persona and calls setCoworkerPersona", async () => {
    const status = mockStatus();
    const onStatus = vi.fn();
    const setSpy = vi.spyOn(api, "setCoworkerPersona").mockResolvedValue({
      ...status,
      persona: status.personas![0],
    });

    render(
      <CoworkerPersonaControl
        client={client}
        sessionKey="s1"
        token="tok"
        status={status}
        onStatus={onStatus}
      />,
    );

    fireEvent.click(screen.getByTestId("persona-control-btn"));
    const option = await screen.findByTestId("persona-option-researcher");
    fireEvent.click(option);

    expect(setSpy).toHaveBeenCalledWith(client, "s1", "researcher");
  });

  it("displays active persona and allows clearing it", async () => {
    const status = mockStatus({
      persona: {
        id: "researcher",
        name: "Deep Researcher",
        emoji: "🔎",
        preset: "sonnet",
      },
    });
    const onStatus = vi.fn();
    const setSpy = vi.spyOn(api, "setCoworkerPersona").mockResolvedValue({
      ...status,
      persona: null,
    });

    render(
      <CoworkerPersonaControl
        client={client}
        sessionKey="s1"
        token="tok"
        status={status}
        onStatus={onStatus}
      />,
    );

    const btn = screen.getByTestId("persona-control-btn");
    expect(btn).toHaveTextContent("Deep Researcher");
    expect(btn).toHaveTextContent("🔎");

    fireEvent.click(btn);
    const clearBtn = await screen.findByTestId("persona-clear-btn");
    fireEvent.click(clearBtn);

    expect(setSpy).toHaveBeenCalledWith(client, "s1", null);
  });

  it("shows warm cache warning when prompt cache is warm", async () => {
    const status = mockStatus({
      caching: {
        is_warm: true,
        hit_rate: 0.8,
        read_tokens: 1000,
        written_tokens: 0,
        input_tokens: 1200,
        last_request: null,
        recent_requests: [],
      },
    });

    render(
      <CoworkerPersonaControl
        client={client}
        sessionKey="s1"
        token="tok"
        status={status}
        onStatus={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByTestId("persona-control-btn"));
    expect(await screen.findByTestId("persona-cache-warning")).toBeInTheDocument();
  });
});

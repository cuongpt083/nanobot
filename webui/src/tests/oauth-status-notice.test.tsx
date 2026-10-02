import { act, fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { OAuthStatusNotice } from "@/components/OAuthStatusNotice";
import type { OAuthStatusEvent } from "@/lib/nanobot-client";
import { ClientProvider } from "@/providers/ClientProvider";

function renderNotice(onOpenModelSettings?: () => void) {
  let emit: ((event: OAuthStatusEvent) => void) | null = null;
  const client = {
    onOAuthStatus: (handler: (event: OAuthStatusEvent) => void) => {
      emit = handler;
      return () => {
        emit = null;
      };
    },
  };
  render(
    <ClientProvider client={client as never} token="tok">
      <OAuthStatusNotice onOpenModelSettings={onOpenModelSettings} />
    </ClientProvider>,
  );
  return {
    fire: (event: OAuthStatusEvent) => act(() => emit?.(event)),
  };
}

describe("OAuthStatusNotice", () => {
  it("shows a sign-in banner with an action on reauth_required", () => {
    const onOpenModelSettings = vi.fn();
    const { fire } = renderNotice(onOpenModelSettings);

    fire({ provider: "anthropic_oauth", status: "reauth_required" });

    const banner = screen.getByRole("alert");
    expect(banner).toHaveTextContent("Anthropic (OAuth) authorization expired");
    fireEvent.click(screen.getByRole("button", { name: "Open model settings" }));
    expect(onOpenModelSettings).toHaveBeenCalledTimes(1);
  });

  it("shows a transient toast on refreshed", () => {
    const { fire } = renderNotice();

    fire({ provider: "anthropic_oauth", status: "refreshed" });

    expect(screen.getByRole("status")).toHaveTextContent(
      "Anthropic (OAuth) access token refreshed.",
    );
  });

  it("dismisses the reauth banner", () => {
    const { fire } = renderNotice();
    fire({ provider: "anthropic_oauth", status: "reauth_required" });
    expect(screen.getByRole("alert")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Dismiss" }));

    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});

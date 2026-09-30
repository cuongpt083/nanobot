import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import {
  CoworkerMessageCard,
  parseCoworkerMessage,
} from "@/components/coworker/CoworkerMessageCard";

describe("CoworkerMessageCard parser and render", () => {
  it("parses auto-advisor-review message", () => {
    const text = "[auto-advisor-review]\n\nFocus: Review system architecture";
    const data = parseCoworkerMessage(text);
    expect(data).not.toBeNull();
    expect(data?.kind).toBe("advisor");
    expect(data?.body).toContain("Review system architecture");
  });

  it("parses auto-room message with mention", () => {
    const text = "[auto-room] @reviewer Please check code style";
    const data = parseCoworkerMessage(text);
    expect(data).not.toBeNull();
    expect(data?.kind).toBe("room");
    expect(data?.target).toBe("@reviewer");
    expect(data?.body).toBe("Please check code style");
  });

  it("parses auto-coding-result message", () => {
    const text = "[auto-coding-result] Task ct-20260930-100000-abcd completed with status succeeded\n+5 -2 in 1 file";
    const data = parseCoworkerMessage(text);
    expect(data).not.toBeNull();
    expect(data?.kind).toBe("coding");
    expect(data?.target).toBe("ct-20260930-100000-abcd");
    expect(data?.body).toContain("+5 -2 in 1 file");
  });

  it("returns null for ordinary user message", () => {
    const data = parseCoworkerMessage("Hello, how are you?");
    expect(data).toBeNull();
  });

  it("renders advisor card", () => {
    render(
      <CoworkerMessageCard
        data={{
          kind: "advisor",
          body: "Focus on database indexing",
        }}
      />,
    );
    expect(screen.getByText(/Senior Advisor Review/i)).toBeInTheDocument();
    expect(screen.getByText(/Focus on database indexing/i)).toBeInTheDocument();
  });

  it("renders room handoff card", () => {
    render(
      <CoworkerMessageCard
        data={{
          kind: "room",
          target: "@coder",
          body: "Implement the login endpoint",
        }}
      />,
    );
    expect(screen.getByText(/Room Teammate Handoff/i)).toBeInTheDocument();
    expect(screen.getByText("@coder")).toBeInTheDocument();
    expect(screen.getByText("Implement the login endpoint")).toBeInTheDocument();
  });
});

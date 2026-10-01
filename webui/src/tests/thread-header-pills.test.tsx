import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { CoworkerParticipantsStrip } from "@/components/coworker/CoworkerParticipants";
import { ThreadHeader } from "@/components/thread/ThreadHeader";
import type { CoworkerParticipant } from "@/lib/types";

const chip: CoworkerParticipant = {
  id: "advisor",
  kind: "advisor",
  label: "Advisor",
  engine: "preset:default",
  state: "working",
  task: null,
  since: null,
  detail: {},
};

describe("thread header pills", () => {
  it("does not force labelled pills into the square icon-button size", () => {
    render(
      <ThreadHeader
        title="t"
        onToggleSidebar={() => {}}
        theme="light"
        onToggleTheme={() => {}}
        coworkerInspectorAction={<button data-header-pill="">Persona</button>}
      />,
    );
    const group = screen.getByText("Persona").parentElement as HTMLElement;
    // The square 28px rule must exclude opted-out pills, otherwise their labels overflow and overlap.
    expect(group.className).toContain("[&_button:not([data-header-pill])]:w-7");
    expect(group.className).not.toMatch(/(^|\s)\[&_button\]:w-7/);
  });

  it("marks participant chips as pills", () => {
    render(<CoworkerParticipantsStrip participants={[chip]} />);
    expect(screen.getByRole("button", { name: /Advisor/ })).toHaveAttribute("data-header-pill");
  });
});

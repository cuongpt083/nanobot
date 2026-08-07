import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { AssistantFeedbackActions } from "@/components/AssistantFeedbackActions";

// Mock react-i18next
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, fallback: string) => fallback,
  }),
}));

describe("AssistantFeedbackActions", () => {
  it("renders four feedback buttons when turnId is present", () => {
    render(<AssistantFeedbackActions turnId="turn_123" />);

    expect(screen.getByTitle("Helpful")).toBeInTheDocument();
    expect(screen.getByTitle("Incorrect")).toBeInTheDocument();
    expect(screen.getByTitle("Retry")).toBeInTheDocument();
    expect(screen.getByTitle("Explain More")).toBeInTheDocument();
  });

  it("invokes callback with expected kind on click", () => {
    const onFeedback = vi.fn();
    render(<AssistantFeedbackActions turnId="turn_123" onFeedback={onFeedback} />);

    fireEvent.click(screen.getByTitle("Helpful"));
    expect(onFeedback).toHaveBeenCalledWith("helpful");

    fireEvent.click(screen.getByTitle("Retry"));
    expect(onFeedback).toHaveBeenCalledWith("retry");
  });
});

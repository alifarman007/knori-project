import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import {
  CORRECTION_MAX_LENGTH,
  CorrectionSheet,
  validateCorrection,
} from "@/components/recognition/correction-sheet";

const TITLE = "You work things out on the page";

describe("validateCorrection", () => {
  it("insists on something to reason with", () => {
    expect(validateCorrection("")).toMatch(/what is actually true/i);
    expect(validateCorrection("  ")).toMatch(/what is actually true/i);
    expect(validateCorrection("no")).toMatch(/what is actually true/i);
  });

  it("accepts a short sentence", () => {
    expect(validateCorrection("I decide first, then write.")).toBeUndefined();
  });

  it("rejects anything past the cap", () => {
    expect(validateCorrection("x".repeat(CORRECTION_MAX_LENGTH + 1))).toMatch(/longer than/i);
  });
});

describe("CorrectionSheet", () => {
  function open(onSubmit = vi.fn()) {
    render(<CorrectionSheet open onClose={vi.fn()} title={TITLE} onSubmit={onSubmit} />);
    return onSubmit;
  }

  it("shows the claim being corrected, so nobody argues from memory", () => {
    open();
    expect(screen.getByText(TITLE)).toBeInTheDocument();
  });

  it("will not submit an empty correction", async () => {
    const user = userEvent.setup();
    const onSubmit = open();

    await user.click(screen.getByRole("button", { name: /save the correction/i }));

    expect(onSubmit).not.toHaveBeenCalled();
    expect(screen.getByText(/a sentence is enough/i)).toBeInTheDocument();
  });

  it("submits the text with the chosen reason, and treats the reason as optional", async () => {
    const user = userEvent.setup();
    const onSubmit = open();

    await user.type(screen.getByLabelText(/what is actually true/i), "I decide first, then write.");
    await user.click(screen.getByRole("button", { name: /save the correction/i }));
    expect(onSubmit).toHaveBeenCalledWith({ correction_text: "I decide first, then write." });

    await user.click(screen.getByRole("button", { name: /not anymore/i }));
    await user.click(screen.getByRole("button", { name: /save the correction/i }));
    expect(onSubmit).toHaveBeenLastCalledWith({
      correction_text: "I decide first, then write.",
      reason_code: "outdated",
    });
  });

  it("lets a reason chip be unpicked", async () => {
    const user = userEvent.setup();
    open();

    const chip = screen.getByRole("button", { name: /partly right/i });
    await user.click(chip);
    expect(chip).toHaveAttribute("aria-pressed", "true");
    await user.click(chip);
    expect(chip).toHaveAttribute("aria-pressed", "false");
  });
});

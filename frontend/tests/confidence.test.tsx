import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { ConfidenceBadge } from "@/components/recognition/confidence-badge";
import { confidenceInWords, evidenceSummary } from "@/lib/format";
import { CONFIDENCE_SHORT, REASON_CHIPS, REASON_LABEL } from "@/lib/labels";

describe("confidence wording", () => {
  it("never puts a number in front of the person", () => {
    for (const label of ["likely", "strong"] as const) {
      const words = confidenceInWords(label);
      expect(words).not.toMatch(/\d/);
      expect(CONFIDENCE_SHORT[label]).not.toMatch(/\d|%/);
    }
  });

  it("says a likely card is a first impression, not a conclusion", () => {
    expect(confidenceInWords("likely")).toMatch(/first impression/i);
    expect(confidenceInWords("likely")).toMatch(/not a conclusion/i);
  });

  it("says a strong card holds across days with nothing against it", () => {
    expect(confidenceInWords("strong")).toMatch(/different days/i);
    expect(confidenceInWords("strong")).toMatch(/nothing pulling against/i);
  });

  it("reaches the explanation from the keyboard, not only on hover", async () => {
    const user = userEvent.setup();
    render(<ConfidenceBadge label="likely" />);

    const trigger = screen.getByRole("button");
    expect(screen.getByRole("tooltip", { hidden: true })).not.toBeVisible();

    await user.click(trigger);
    expect(screen.getByRole("tooltip")).toHaveTextContent(/first impression/i);
    expect(trigger).toHaveAttribute("aria-describedby");
  });
});

describe("evidence wording", () => {
  it("counts in the person's own terms, never in signals", () => {
    expect(evidenceSummary(3, 2)).toBe("based on 3 things you said across 2 days");
    expect(evidenceSummary(1, 1)).toBe("based on 1 thing you said");
  });
});

describe("correction reasons", () => {
  it("offers the five plan.md chips, each with a label the person would use", () => {
    expect(REASON_CHIPS.map((chip) => chip.code)).toEqual([
      "partly_true",
      "not_true",
      "outdated",
      "too_personal",
      "not_useful",
    ]);
    for (const chip of REASON_CHIPS) {
      expect(REASON_LABEL[chip.code]).toBe(chip.label);
      expect(chip.hint.length).toBeGreaterThan(0);
    }
  });
});

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { RecognitionCard } from "@/components/recognition/recognition-card";
import { SAMPLE_PROVENANCE, SAMPLE_RECOGNITION } from "@/lib/mock";
import type { FeedbackAction } from "@/lib/types";

describe("RecognitionCard", () => {
  it("shows every quote with its date, and counts them in the person's words", () => {
    render(
      <RecognitionCard
        recognition={SAMPLE_RECOGNITION}
        provenance={SAMPLE_PROVENANCE}
        defaultEvidenceOpen
      />,
    );

    expect(screen.getByText(SAMPLE_RECOGNITION.title)).toBeInTheDocument();
    // Three supports falling on two calendar days — rule R3's minimum shape.
    expect(screen.getByText(/based on 3 things you said across 2 days/)).toBeInTheDocument();

    for (const item of SAMPLE_PROVENANCE) {
      expect(screen.getByText(new RegExp(escapeRegExp(item.quote_text)))).toBeInTheDocument();
    }
    expect(screen.getByText("15 Sep")).toBeInTheDocument();
  });

  it("keeps the evidence collapsed until asked, and announces the disclosure", async () => {
    const user = userEvent.setup();
    render(<RecognitionCard recognition={SAMPLE_RECOGNITION} provenance={SAMPLE_PROVENANCE} />);

    const toggle = screen.getByRole("button", { name: /based on 3 things/ });
    expect(toggle).toHaveAttribute("aria-expanded", "false");

    await user.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText(new RegExp(escapeRegExp(SAMPLE_PROVENANCE[0]!.quote_text)))).toBeVisible();
  });

  it("fires the matching action for each of the four buttons", async () => {
    const user = userEvent.setup();
    const onAction = vi.fn<(action: FeedbackAction) => void>();
    render(
      <RecognitionCard
        recognition={SAMPLE_RECOGNITION}
        provenance={SAMPLE_PROVENANCE}
        onAction={onAction}
      />,
    );

    await user.click(screen.getByRole("button", { name: /that.s right/i }));
    await user.click(screen.getByRole("button", { name: /not quite/i }));
    await user.click(screen.getByRole("button", { name: /not true/i }));
    await user.click(screen.getByRole("button", { name: /not now/i }));

    expect(onAction.mock.calls.map(([action]) => action)).toEqual([
      "accept",
      "correct",
      "reject",
      "dismiss",
    ]);
  });

  it("replaces the buttons with a plain sentence once the person has answered", () => {
    render(
      <RecognitionCard
        recognition={{ ...SAMPLE_RECOGNITION, state: "rejected" }}
        provenance={SAMPLE_PROVENANCE}
        onAction={vi.fn()}
      />,
    );

    expect(screen.getByText(/will not raise it again/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /that.s right/i })).not.toBeInTheDocument();
  });
});

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

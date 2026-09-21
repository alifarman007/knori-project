import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { Composer, MAX_MESSAGE_LENGTH } from "@/components/chat/composer";

function setup(props: Partial<React.ComponentProps<typeof Composer>> = {}) {
  const onSend = vi.fn();
  const onStop = vi.fn();
  render(<Composer onSend={onSend} onStop={onStop} streaming={false} {...props} />);
  return { onSend, onStop, box: screen.getByLabelText("Message") };
}

describe("chat composer", () => {
  it("sends on Enter and clears the box", async () => {
    const user = userEvent.setup();
    const { onSend, box } = setup();

    await user.type(box, "  it was a long week  ");
    await user.keyboard("{Enter}");

    expect(onSend).toHaveBeenCalledWith("it was a long week");
    expect(box).toHaveValue("");
  });

  it("starts a new line on Shift+Enter without sending", async () => {
    const user = userEvent.setup();
    const { onSend, box } = setup();

    await user.type(box, "first");
    await user.keyboard("{Shift>}{Enter}{/Shift}");
    await user.type(box, "second");

    expect(onSend).not.toHaveBeenCalled();
    expect(box).toHaveValue("first\nsecond");
  });

  it("refuses to send nothing", async () => {
    const user = userEvent.setup();
    const { onSend, box } = setup();

    await user.type(box, "   ");
    await user.keyboard("{Enter}");

    expect(onSend).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: /send message/i })).toBeDisabled();
  });

  it("blocks a message past the 8k cap and says how far over it is", async () => {
    const { onSend, box } = setup();

    // Typing 8k characters one keypress at a time is far too slow for a test.
    const tooLong = "x".repeat(MAX_MESSAGE_LENGTH + 1);
    const user = userEvent.setup();
    await user.click(box);
    await user.paste(tooLong);

    expect(box).toHaveAttribute("aria-invalid", "true");
    expect(
      screen.getByText(`${(MAX_MESSAGE_LENGTH + 1).toLocaleString()} / ${MAX_MESSAGE_LENGTH.toLocaleString()}`),
    ).toBeInTheDocument();

    await user.keyboard("{Enter}");
    expect(onSend).not.toHaveBeenCalled();
  });

  it("offers Stop instead of Send while a reply is streaming", async () => {
    const user = userEvent.setup();
    const { onStop } = setup({ streaming: true });

    expect(screen.queryByRole("button", { name: /send message/i })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /stop/i }));
    expect(onStop).toHaveBeenCalled();
  });
});

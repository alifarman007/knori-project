import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { Button } from "@/components/ui/button";

describe("Button", () => {
  it("cannot be clicked while loading, and says so to assistive tech", async () => {
    const user = userEvent.setup();
    const onClick = vi.fn();
    render(
      <Button loading onClick={onClick}>
        Create account
      </Button>,
    );

    const button = screen.getByRole("button", { name: /create account/i });
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute("aria-busy", "true");

    await user.click(button);
    expect(onClick).not.toHaveBeenCalled();
  });

  it("swaps the label when loadingText is given, and keeps it otherwise", () => {
    const { rerender } = render(
      <Button loading loadingText="Signing in…">
        Sign in
      </Button>,
    );
    expect(screen.getByRole("button", { name: /signing in/i })).toBeInTheDocument();

    rerender(<Button>Sign in</Button>);
    const idle = screen.getByRole("button", { name: /sign in/i });
    expect(idle).toBeEnabled();
    expect(idle).not.toHaveAttribute("aria-busy");
  });
});

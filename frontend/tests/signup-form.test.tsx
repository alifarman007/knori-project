import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import SignupPage from "@/app/(auth)/signup/page";

describe("signup form", () => {
  it("refuses to submit and names every problem inline", async () => {
    const user = userEvent.setup();
    render(<SignupPage />);

    await user.click(screen.getByRole("button", { name: /create account/i }));

    expect(screen.getByText(/tell knori what to call you/i)).toBeInTheDocument();
    expect(screen.getByText(/enter your email address/i)).toBeInTheDocument();
    expect(screen.getByText(/choose a password/i)).toBeInTheDocument();
    expect(screen.getByText(/invite code is needed/i)).toBeInTheDocument();

    // Still on the form, not on the "check your email" panel.
    expect(screen.queryByText(/check your email/i)).not.toBeInTheDocument();
  });

  it("marks a short password invalid on blur and wires the message to the input", async () => {
    const user = userEvent.setup();
    render(<SignupPage />);

    const password = screen.getByLabelText(/^password$/i);
    await user.type(password, "short");
    await user.tab();

    const message = screen.getByText(/at least 10 characters/i);
    expect(password).toHaveAttribute("aria-invalid", "true");
    expect(password.getAttribute("aria-describedby")).toContain(message.id);
  });

  it("clears an error as soon as the person starts fixing it", async () => {
    const user = userEvent.setup();
    render(<SignupPage />);

    const email = screen.getByLabelText(/email/i);
    await user.type(email, "not-an-address");
    await user.tab();
    expect(screen.getByText(/does not look like an email address/i)).toBeInTheDocument();

    await user.type(email, "@example.com");
    expect(screen.queryByText(/does not look like an email address/i)).not.toBeInTheDocument();
  });
});

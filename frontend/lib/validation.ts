/**
 * Form rules, kept identical to the ones the API enforces (plan §7).
 *
 * Client-side validation exists to make the form pleasant, not to make it safe:
 * every rule here is checked again on the server, and a server error always
 * wins over a local one.
 */

/** Deliberately loose: the only real test of an address is sending mail to it. */
const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/;

export const PASSWORD_MIN_LENGTH = 10;

export function validateEmail(value: string): string | undefined {
  const email = value.trim();
  if (!email) return "Enter your email address.";
  if (!EMAIL.test(email)) return "That does not look like an email address.";
  return undefined;
}

export function validatePassword(value: string): string | undefined {
  if (!value) return "Choose a password.";
  if (value.length < PASSWORD_MIN_LENGTH) {
    return `Use at least ${PASSWORD_MIN_LENGTH} characters — length matters more than symbols.`;
  }
  return undefined;
}

export function validateCurrentPassword(value: string): string | undefined {
  if (!value) return "Enter your password.";
  return undefined;
}

export function validateDisplayName(value: string): string | undefined {
  const name = value.trim();
  if (!name) return "Tell KnoRI what to call you.";
  if (name.length > 80) return "That is longer than 80 characters.";
  return undefined;
}

export function validateInviteCode(value: string, required: boolean): string | undefined {
  if (!required) return undefined;
  if (!value.trim()) return "An invite code is needed while KnoRI is in beta.";
  return undefined;
}

export function validateMatch(value: string, other: string): string | undefined {
  if (value !== other) return "The two passwords do not match.";
  return undefined;
}

/** A rough four-step meter. It advises; it never blocks. */
export function passwordStrength(value: string): { score: 0 | 1 | 2 | 3 | 4; label: string } {
  if (!value) return { score: 0, label: "" };
  let score = 0;
  if (value.length >= PASSWORD_MIN_LENGTH) score += 1;
  if (value.length >= 16) score += 1;
  if (/\s/.test(value.trim())) score += 1;
  if (/[^A-Za-z0-9]/.test(value) || (/[A-Za-z]/.test(value) && /\d/.test(value))) score += 1;
  const clamped = Math.min(score, 4) as 0 | 1 | 2 | 3 | 4;
  const labels = ["", "Short", "Fine", "Good", "Strong"] as const;
  return { score: clamped, label: labels[clamped] };
}

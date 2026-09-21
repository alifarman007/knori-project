import type { OnboardingQuestion } from "@/lib/types";

/** The legal texts in force during the beta (plan §8, `draft-0`). */
export const TOS_VERSION = "draft-0";
export const PRIVACY_VERSION = "draft-0";

/**
 * The three scripted questions (plan §8).
 *
 * `GET /onboarding` is the source of truth and these are the fallback, so the
 * screen still works if that call fails or the API has not started sending
 * them. They are deliberately open: the point of the first conversation is to
 * get the person's own words on the page, not to fill in a form.
 */
export const DEFAULT_QUESTIONS: readonly OnboardingQuestion[] = [
  {
    index: 1,
    prompt: "What is going on in your life lately?",
    note: "Whatever is taking up room. A sentence is fine; a paragraph is better.",
  },
  {
    index: 2,
    prompt: "What would you like me to notice — and what should I leave alone?",
    note: "Anything you name here, KnoRI will not reason about.",
  },
  {
    index: 3,
    prompt: "How do you want me to talk to you?",
    note: "Blunt, gentle, short, thorough. Say it plainly and it will stick.",
  },
];

export const ANSWER_MIN_LENGTH = 2;
export const ANSWER_MAX_LENGTH = 2_000;

export function validateAnswer(text: string): string | undefined {
  const trimmed = text.trim();
  if (trimmed.length < ANSWER_MIN_LENGTH) return "Write a line before moving on.";
  if (trimmed.length > ANSWER_MAX_LENGTH) {
    return `That is longer than ${ANSWER_MAX_LENGTH} characters.`;
  }
  return undefined;
}

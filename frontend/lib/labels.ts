/**
 * The words KnoRI uses for its own vocabulary.
 *
 * Nothing in the UI prints a raw enum. "preference" is a database value;
 * "What you prefer" is what a person reads. Keeping the two apart here means a
 * rename in the schema never leaks onto a screen, and the tone stays consistent
 * across four different surfaces.
 */

import type {
  AssertionKind,
  ConfidenceLabel,
  MemoryKind,
  MemorySourceKind,
  MemoryStatus,
  ReasonCode,
} from "@/lib/types";

export const MEMORY_KIND_LABEL: Record<MemoryKind, string> = {
  fact: "Facts",
  preference: "Preferences",
  goal: "Goals",
  event: "Things that happened",
  routine: "Routines",
  constraint: "Limits",
  relationship: "People in your life",
};

/** Order on `/app/memory`: the groups people look for first come first. */
export const MEMORY_KIND_ORDER: readonly MemoryKind[] = [
  "fact",
  "preference",
  "goal",
  "routine",
  "constraint",
  "event",
  "relationship",
];

export const MEMORY_KIND_HELP: Record<MemoryKind, string> = {
  fact: "Plain things you told KnoRI about your situation.",
  preference: "How you like things done.",
  goal: "What you said you are working towards.",
  event: "Something that happened, with the day you mentioned it.",
  routine: "Things you do regularly.",
  constraint: "What you cannot or will not do.",
  relationship: "Your own words about the people around you — nothing about them.",
};

export const MEMORY_SOURCE_LABEL: Record<MemorySourceKind, string> = {
  extracted: "from what you said",
  onboarding: "from your first answers",
  user_added: "you added this",
  user_edited: "you edited this",
  correction: "from a correction",
};

export const MEMORY_STATUS_LABEL: Record<MemoryStatus, string> = {
  active: "In use",
  superseded: "Replaced",
  retracted: "Retracted",
};

export const ASSERTION_KIND_LABEL: Record<AssertionKind, string> = {
  affirm: "You confirmed",
  deny: "You denied",
  amend: "You corrected",
  scope: "You set a limit",
};

/** The chips on the correction sheet, in the order plan §8 lists them. */
export const REASON_CHIPS: readonly { code: ReasonCode; label: string; hint: string }[] = [
  { code: "partly_true", label: "Partly right", hint: "Some of it lands, some of it does not." },
  { code: "not_true", label: "Not true", hint: "KnoRI read this wrong." },
  { code: "outdated", label: "Not anymore", hint: "It was true once. It is not now." },
  { code: "too_personal", label: "Too personal", hint: "Do not reason about this." },
  { code: "not_useful", label: "Not useful", hint: "Accurate, but not worth telling me." },
];

export const REASON_LABEL: Record<ReasonCode, string> = {
  partly_true: "Partly right",
  not_true: "Not true",
  outdated: "Not anymore",
  too_personal: "Too personal",
  not_useful: "Not useful",
};

/** Plain-words confidence, used where the badge tooltip is not enough room. */
export const CONFIDENCE_SHORT: Record<ConfidenceLabel, string> = {
  likely: "A first impression",
  strong: "Consistent across several days",
};

/** History timeline wording for `recognition_events.event`. */
const HISTORY_WORDS: Record<string, string> = {
  created: "KnoRI put this together",
  presented: "Shown to you",
  seen: "You opened it",
  accepted: "You said this is right",
  corrected: "You corrected it",
  rejected: "You said this is not true",
  dismissed: "You set it aside",
  withdrawn: "KnoRI withdrew it",
  revised: "KnoRI revised it after your correction",
  superseded: "Replaced by a newer version",
  rescored: "Re-scored after new evidence",
};

export function historyWords(event: string): string {
  return HISTORY_WORDS[event] ?? event.replace(/_/g, " ");
}

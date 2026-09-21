/**
 * TanStack Query keys in one place.
 *
 * Invalidation is the whole reason: when a correction lands, four screens have
 * to become stale at once, and guessing the key strings at each call site is how
 * one of them silently stops updating.
 */

import type { Uuid } from "@/lib/types";

export const keys = {
  session: ["session"] as const,
  settings: ["settings"] as const,

  onboarding: ["onboarding"] as const,

  conversations: ["conversations"] as const,
  conversation: (id: Uuid) => ["conversation", id] as const,
  messages: (id: Uuid) => ["messages", id] as const,

  recognitions: (state?: string) => ["recognitions", state ?? "all"] as const,
  recognition: (id: Uuid) => ["recognition", id] as const,
  recognitionHistory: (id: Uuid) => ["recognition", id, "history"] as const,
  recognitionSummary: ["recognitions", "summary"] as const,
  correctionEffect: (feedbackId: Uuid) => ["correction-effect", feedbackId] as const,

  memoryItems: ["memory", "items"] as const,
  memorySources: (id: Uuid) => ["memory", "sources", id] as const,
  memoryProfile: ["memory", "profile"] as const,
  assertions: ["memory", "assertions"] as const,

  job: (id: Uuid) => ["job", id] as const,
};

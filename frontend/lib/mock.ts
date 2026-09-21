/**
 * Demo content for the screens that ship before the API does.
 *
 * Everything here obeys the same rules the engine does, so the pages never
 * promise something the product cannot deliver: at least two supporting quotes,
 * on at least two different days, and card text that paraphrases rather than
 * repeating a quote word for word (rule R3 and engine rule 12).
 *
 * Replace these with real queries as each endpoint lands; nothing else in the
 * UI imports this file.
 */

import type { ProvenanceItem, Recognition, RecognitionDetail } from "@/lib/types";

function quote(
  partial: Pick<ProvenanceItem, "id" | "quote_text" | "message_created_at" | "seq"> &
    Partial<ProvenanceItem>,
): ProvenanceItem {
  return {
    kind: "signal",
    role: "supports",
    weight: 1,
    quote_start: 0,
    quote_end: partial.quote_text.length,
    message_id: `m-${partial.id}`,
    conversation_id: "c-1",
    conversation_title: "Untitled conversation",
    scrubbed: false,
    note: null,
    display_order: 0,
    ...partial,
  };
}

export const SAMPLE_PROVENANCE: ProvenanceItem[] = [
  quote({
    id: "p1",
    display_order: 0,
    seq: 12,
    quote_text:
      "honestly I don't know what I think about it until I've written it out properly",
    conversation_title: "Deciding about the move",
    message_created_at: "2026-09-15T21:40:00+06:00",
  }),
  quote({
    id: "p2",
    display_order: 1,
    seq: 4,
    quote_text:
      "spent the whole morning on the doc and by the end the answer was kind of obvious",
    conversation_title: "Thursday",
    message_created_at: "2026-09-17T09:12:00+06:00",
  }),
  quote({
    id: "p3",
    display_order: 2,
    seq: 9,
    quote_text: "wrote three pages about it last night and slept fine for once",
    conversation_title: "Thursday",
    message_created_at: "2026-09-17T22:05:00+06:00",
  }),
];

export const SAMPLE_RECOGNITION: Recognition = {
  id: "r-writing",
  interpretation_id: "11111111-1111-4111-8111-111111111111",
  interpretation_version: 1,
  kind: "pattern",
  title: "You work things out on the page",
  body:
    "It looks like writing is how you reach a decision rather than how you record one. Twice you described a choice only settling once it was down in full, and both times the relief came after the writing, not before it.",
  confidence: {
    value: 0.73,
    label: "likely",
    plain: "Based on 2 things you said across 2 days; nothing you said pointed the other way.",
    supports: 2,
    contradicts: 0,
    distinct_days: 2,
    span_hours: 53.0,
    deleted_sources: 0,
  },
  state: "presented",
  supersedes_id: null,
  created_at: "2026-09-18T08:30:00+06:00",
  presented_at: "2026-09-18T08:30:00+06:00",
  resolved_at: null,
  feedback_action: null,
  correction_effect_status: null,
};

export const SAMPLE_DETAIL: RecognitionDetail = {
  ...SAMPLE_RECOGNITION,
  explanation:
    "Three things you said across two days point the same way, and nothing you have said pulls against it. KnoRI is showing this as a first impression, not a conclusion — you can correct it and the correction will change what it reasons with next time.",
  confidence_in_words:
    "Enough of what you said points this way to be worth showing you — but it is a first impression, not a conclusion.",
  interpretation: {
    id: "i-writing",
    version: 1,
    kind: "pattern",
    topic: "work_habits",
    statement: "The user reaches decisions by writing them out in full.",
  },
  provenance: SAMPLE_PROVENANCE,
  feedback: null,
  correction_effect: null,
};

export const SAMPLE_FEED: Recognition[] = [
  SAMPLE_RECOGNITION,
  {
    id: "r-directness",
    interpretation_id: "21111111-1111-4111-8111-111111111111",
    interpretation_version: 1,
    kind: "preference",
    title: "You would rather have the blunt version",
    body:
      "When people soften things for you, you seem to spend the energy working out what was left out. You have asked for the direct answer twice now, in different situations.",
    confidence: {
      value: 0.82,
      label: "strong",
      plain: "Based on 3 things you said across 3 days; nothing you said pointed the other way.",
      supports: 3,
      contradicts: 0,
      distinct_days: 3,
      span_hours: 79.5,
      deleted_sources: 0,
    },
    state: "accepted",
    supersedes_id: null,
    created_at: "2026-09-12T10:05:00+06:00",
    presented_at: "2026-09-12T10:05:00+06:00",
    resolved_at: "2026-09-12T18:20:00+06:00",
    feedback_action: null,
    correction_effect_status: null,
  },
  {
    id: "r-tension",
    interpretation_id: "31111111-1111-4111-8111-111111111111",
    interpretation_version: 1,
    kind: "tension",
    title: "You want the team to decide, and you want the call to be yours",
    body:
      "You have described wanting people to own their work, and in the same week described stepping back in because the direction felt wrong. Both seem true at once rather than one replacing the other.",
    confidence: {
      value: 0.71,
      label: "likely",
      plain: "Based on 2 things you said across 2 days; nothing you said pointed the other way.",
      supports: 2,
      contradicts: 0,
      distinct_days: 2,
      span_hours: 53.0,
      deleted_sources: 0,
    },
    state: "corrected",
    supersedes_id: null,
    created_at: "2026-09-09T16:40:00+06:00",
    presented_at: "2026-09-09T16:40:00+06:00",
    resolved_at: "2026-09-10T08:02:00+06:00",
    feedback_action: null,
    correction_effect_status: null,
  },
];

export const DEMO_USER = { display_name: "Alif Arman", email: "you@example.com" };

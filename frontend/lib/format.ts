/**
 * Turning data into the words KnoRI uses on screen.
 *
 * Two house rules live here:
 *   - dates are relative while that is still honest ("yesterday"), absolute
 *     after that, because "14 days ago" makes nobody feel understood;
 *   - evidence is counted in the person's own terms — "3 things you said
 *     across 2 days" — never "3 signals".
 *
 * Dates are formatted from the wall-clock fields in the timestamp rather than
 * through `Intl`. Server and client then always produce the same string, which
 * is what keeps a server-rendered page from flickering on hydration. It also
 * means the API should send timestamps in the person's own timezone — the same
 * timezone rule R3 counts calendar days in.
 */

import type { ConfidenceLabel, ProvenanceItem, RecognitionKind, RecognitionState } from "@/lib/types";

const MONTHS = [
  "Jan",
  "Feb",
  "Mar",
  "Apr",
  "May",
  "Jun",
  "Jul",
  "Aug",
  "Sep",
  "Oct",
  "Nov",
  "Dec",
] as const;

const MS_PER_DAY = 86_400_000;

const TIMESTAMP =
  /^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?$/;

interface Parts {
  year: number;
  month: number;
  day: number;
  hour: number;
  minute: number;
}

function parts(value: Date | string): Parts | null {
  if (value instanceof Date) {
    if (Number.isNaN(value.getTime())) return null;
    return {
      year: value.getFullYear(),
      month: value.getMonth(),
      day: value.getDate(),
      hour: value.getHours(),
      minute: value.getMinutes(),
    };
  }
  const match = TIMESTAMP.exec(value.trim());
  if (!match) return null;
  return {
    year: Number(match[1]),
    month: Number(match[2]) - 1,
    day: Number(match[3]),
    hour: Number(match[4]),
    minute: Number(match[5]),
  };
}

function dayNumber(value: Parts): number {
  return Date.UTC(value.year, value.month, value.day) / MS_PER_DAY;
}

function todayNumber(now: Date): number {
  return Date.UTC(now.getFullYear(), now.getMonth(), now.getDate()) / MS_PER_DAY;
}

export function formatDate(value: Date | string, now: Date = new Date()): string {
  const date = parts(value);
  if (!date) return "";
  const month = MONTHS[date.month] ?? "";
  return date.year === now.getFullYear()
    ? `${date.day} ${month}`
    : `${date.day} ${month} ${date.year}`;
}

export function formatTime(value: Date | string): string {
  const date = parts(value);
  if (!date) return "";
  return `${String(date.hour).padStart(2, "0")}:${String(date.minute).padStart(2, "0")}`;
}

export function formatDateTime(value: Date | string, now: Date = new Date()): string {
  const date = parts(value);
  if (!date) return "";
  return `${formatDate(value, now)} at ${formatTime(value)}`;
}

/** "today" · "yesterday" · "4 days ago" · "12 Mar". */
export function relativeDate(value: Date | string, now: Date = new Date()): string {
  const date = parts(value);
  if (!date) return "";
  const days = todayNumber(now) - dayNumber(date);
  if (days < 0) return formatDate(value, now);
  if (days === 0) return "today";
  if (days === 1) return "yesterday";
  if (days < 7) return `${days} days ago`;
  return formatDate(value, now);
}

/** Relative down to the minute, for chat and toasts. */
export function relativeTime(value: Date | string, now: Date = new Date()): string {
  const date = parts(value);
  if (!date) return "";
  const days = todayNumber(now) - dayNumber(date);
  if (days === 0) {
    const minutes = (now.getHours() - date.hour) * 60 + (now.getMinutes() - date.minute);
    if (minutes < 1) return "just now";
    if (minutes < 60) return `${minutes} min ago`;
    return formatTime(value);
  }
  return relativeDate(value, now);
}

export function pluralise(count: number, one: string, many = `${one}s`): string {
  return count === 1 ? one : many;
}

/**
 * "based on 3 things you said across 2 days" — the line under every card.
 * Rule R3 means the honest minimum is always 2 things on 2 days.
 */
export function evidenceSummary(thingCount: number, dayCount: number): string {
  const things = `${thingCount} ${pluralise(thingCount, "thing")} you said`;
  if (dayCount <= 1) return `based on ${things}`;
  return `based on ${things} across ${dayCount} days`;
}

/** Count supports and the distinct calendar days they fall on. */
export function summariseProvenance(items: readonly ProvenanceItem[]): {
  thingCount: number;
  dayCount: number;
} {
  const supports = items.filter((item) => item.role === "supports");
  const days = new Set<number>();
  for (const item of supports) {
    if (!item.message_created_at) continue;
    const date = parts(item.message_created_at);
    if (date) days.add(dayNumber(date));
  }
  return { thingCount: supports.length, dayCount: days.size };
}

/** The tooltip behind the confidence badge. Plain words, no percentages. */
export function confidenceInWords(label: ConfidenceLabel): string {
  return label === "strong"
    ? "Several things you said point the same way, on different days, with nothing pulling against it."
    : "Enough of what you said points this way to be worth showing you — but it is a first impression, not a conclusion.";
}

export const KIND_LABEL: Record<RecognitionKind, string> = {
  pattern: "Pattern",
  preference: "Preference",
  value: "Value",
  tension: "Tension",
};

export const STATE_LABEL: Record<RecognitionState, string> = {
  pending: "New",
  presented: "New",
  accepted: "Accepted",
  corrected: "Corrected",
  rejected: "Rejected",
  dismissed: "Dismissed",
  withdrawn: "Withdrawn",
};

export function truncate(text: string, max: number): string {
  if (text.length <= max) return text;
  return `${text.slice(0, max - 1).trimEnd()}…`;
}

export function initials(name: string): string {
  const words = name.trim().split(/\s+/).filter(Boolean);
  if (words.length === 0) return "?";
  const first = words[0]?.[0] ?? "";
  const last = words.length > 1 ? (words[words.length - 1]?.[0] ?? "") : "";
  return (first + last).toUpperCase();
}

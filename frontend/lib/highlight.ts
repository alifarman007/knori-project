/**
 * The `?m=<seq>&hl=<start>-<end>` deep link (plan §8).
 *
 * A Recognition promises to show the person the exact words it was built from,
 * so "open in chat" has to land on the right message and mark the right
 * characters — not a fuzzy text search that could highlight a later sentence
 * that happens to match. The offsets come from `signals`, where they were
 * verified against `message.content[start:end]` before the row was stored.
 *
 * Everything here is pure, so the rule can be tested without a browser.
 */

export interface HighlightTarget {
  seq: number;
  start: number | null;
  end: number | null;
}

export interface Segment {
  text: string;
  marked: boolean;
}

/** Read the target out of a query string. Anything malformed is simply ignored. */
export function parseHighlight(params: URLSearchParams | null): HighlightTarget | null {
  if (!params) return null;
  const seq = Number.parseInt(params.get("m") ?? "", 10);
  if (!Number.isInteger(seq) || seq < 0) return null;

  const range = params.get("hl");
  if (!range) return { seq, start: null, end: null };

  const match = /^(\d+)-(\d+)$/.exec(range);
  if (!match) return { seq, start: null, end: null };

  const start = Number.parseInt(match[1] as string, 10);
  const end = Number.parseInt(match[2] as string, 10);
  if (end <= start) return { seq, start: null, end: null };
  return { seq, start, end };
}

/**
 * Split a message into marked and unmarked runs.
 *
 * Offsets that no longer fit the text — because the message was edited, or the
 * API sent a different revision — produce one unmarked segment rather than a
 * highlight in the wrong place. Showing nothing is honest; showing the wrong
 * words is not.
 */
export function splitForHighlight(
  content: string,
  start: number | null,
  end: number | null,
): Segment[] {
  if (start === null || end === null) return [{ text: content, marked: false }];
  if (start < 0 || end > content.length || end <= start) {
    return [{ text: content, marked: false }];
  }

  const segments: Segment[] = [];
  if (start > 0) segments.push({ text: content.slice(0, start), marked: false });
  segments.push({ text: content.slice(start, end), marked: true });
  if (end < content.length) segments.push({ text: content.slice(end), marked: false });
  return segments;
}

/** The anchor id a message row carries, so the deep link can scroll to it. */
export function messageAnchorId(seq: number): string {
  return `m-${seq}`;
}

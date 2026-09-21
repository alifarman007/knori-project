import { describe, expect, it } from "vitest";

import { messageAnchorId, parseHighlight, splitForHighlight } from "@/lib/highlight";

function params(query: string): URLSearchParams {
  return new URLSearchParams(query);
}

describe("parseHighlight", () => {
  it("reads a message and a character range", () => {
    expect(parseHighlight(params("m=12&hl=4-19"))).toEqual({ seq: 12, start: 4, end: 19 });
  });

  it("accepts a message on its own", () => {
    expect(parseHighlight(params("m=3"))).toEqual({ seq: 3, start: null, end: null });
  });

  it("ignores a malformed or backwards range rather than marking the wrong words", () => {
    expect(parseHighlight(params("m=3&hl=banana"))).toEqual({ seq: 3, start: null, end: null });
    expect(parseHighlight(params("m=3&hl=19-4"))).toEqual({ seq: 3, start: null, end: null });
    expect(parseHighlight(params("m=3&hl=5-5"))).toEqual({ seq: 3, start: null, end: null });
  });

  it("is null without a usable message number", () => {
    expect(parseHighlight(params(""))).toBeNull();
    expect(parseHighlight(params("m=abc"))).toBeNull();
    expect(parseHighlight(params("m=-1"))).toBeNull();
    expect(parseHighlight(null)).toBeNull();
  });
});

describe("splitForHighlight", () => {
  const content = "honestly I don't know what I think until I've written it out";

  it("marks exactly the offsets the signal was stored with", () => {
    const segments = splitForHighlight(content, 9, 30);
    expect(segments.map((segment) => segment.text).join("")).toBe(content);
    expect(segments.filter((segment) => segment.marked)).toHaveLength(1);
    expect(segments.find((segment) => segment.marked)?.text).toBe(content.slice(9, 30));
  });

  it("marks from the very start and to the very end without empty runs", () => {
    expect(splitForHighlight("abcdef", 0, 3)).toEqual([
      { text: "abc", marked: true },
      { text: "def", marked: false },
    ]);
    expect(splitForHighlight("abcdef", 3, 6)).toEqual([
      { text: "abc", marked: false },
      { text: "def", marked: true },
    ]);
  });

  it("marks nothing when the offsets no longer fit the text", () => {
    const plain = [{ text: content, marked: false }];
    expect(splitForHighlight(content, 0, content.length + 5)).toEqual(plain);
    expect(splitForHighlight(content, -2, 4)).toEqual(plain);
    expect(splitForHighlight(content, 20, 10)).toEqual(plain);
    expect(splitForHighlight(content, null, null)).toEqual(plain);
  });
});

describe("messageAnchorId", () => {
  it("matches what the deep link scrolls to", () => {
    expect(messageAnchorId(12)).toBe("m-12");
  });
});

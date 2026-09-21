import { describe, expect, it } from "vitest";

import { evidenceSummary, formatDate, relativeDate, summariseProvenance } from "@/lib/format";
import { SAMPLE_PROVENANCE } from "@/lib/mock";

const NOW = new Date(2026, 8, 21, 12, 0, 0); // 21 September 2026, local

describe("evidenceSummary", () => {
  it("counts in the person's words, not the engine's", () => {
    expect(evidenceSummary(3, 2)).toBe("based on 3 things you said across 2 days");
    expect(evidenceSummary(2, 2)).toBe("based on 2 things you said across 2 days");
    expect(evidenceSummary(1, 1)).toBe("based on 1 thing you said");
  });
});

describe("summariseProvenance", () => {
  it("counts supports and the distinct days they fall on", () => {
    expect(summariseProvenance(SAMPLE_PROVENANCE)).toEqual({ thingCount: 3, dayCount: 2 });
  });

  it("ignores anything that is not supporting evidence", () => {
    const withContradiction = [
      ...SAMPLE_PROVENANCE,
      { ...SAMPLE_PROVENANCE[0]!, id: "x", role: "contradicts" as const },
    ];
    expect(summariseProvenance(withContradiction).thingCount).toBe(3);
  });
});

describe("dates", () => {
  it("reads the wall-clock fields, so server and client agree", () => {
    expect(formatDate("2026-09-15T21:40:00+06:00", NOW)).toBe("15 Sep");
    expect(formatDate("2026-09-15T21:40:00Z", NOW)).toBe("15 Sep");
    expect(formatDate("2024-01-02T00:00:00Z", NOW)).toBe("2 Jan 2024");
  });

  it("stays relative only while that is still honest", () => {
    expect(relativeDate("2026-09-21T08:00:00Z", NOW)).toBe("today");
    expect(relativeDate("2026-09-20T23:50:00Z", NOW)).toBe("yesterday");
    expect(relativeDate("2026-09-18T09:00:00Z", NOW)).toBe("3 days ago");
    expect(relativeDate("2026-09-01T09:00:00Z", NOW)).toBe("1 Sep");
  });
});

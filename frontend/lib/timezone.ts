/**
 * Timezone, which matters more here than in most products.
 *
 * Rule R3 counts "two distinct calendar days" in the person's own timezone, so
 * a wrong zone does not just misprint a date — it can decide whether KnoRI says
 * anything at all. We detect it, show it, and let them change it.
 */

const FALLBACK = "UTC";

/** What the browser thinks the person's timezone is. */
export function detectTimezone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || FALLBACK;
  } catch {
    return FALLBACK;
  }
}

/** "Asia/Dhaka" -> "Asia / Dhaka", which is easier to scan in a list. */
export function timezoneLabel(zone: string): string {
  return zone.split("/").join(" / ").replace(/_/g, " ");
}

/**
 * A short list plus whatever the browser reports, so the common case is one tap
 * and the rare case is still reachable. `Intl.supportedValuesOf` gives the full
 * list where the browser has it.
 */
export function timezoneOptions(current?: string): string[] {
  const zones = new Set<string>();
  const detected = detectTimezone();
  zones.add(detected);
  if (current) zones.add(current);

  try {
    const all = (
      Intl as unknown as { supportedValuesOf?: (key: string) => string[] }
    ).supportedValuesOf?.("timeZone");
    if (all?.length) {
      for (const zone of all) zones.add(zone);
      return [...zones];
    }
  } catch {
    // Older browsers: fall through to the short list.
  }

  for (const zone of COMMON) zones.add(zone);
  return [...zones];
}

const COMMON = [
  "UTC",
  "Europe/London",
  "Europe/Berlin",
  "Europe/Lisbon",
  "America/New_York",
  "America/Chicago",
  "America/Denver",
  "America/Los_Angeles",
  "America/Sao_Paulo",
  "Africa/Lagos",
  "Africa/Nairobi",
  "Asia/Dubai",
  "Asia/Karachi",
  "Asia/Dhaka",
  "Asia/Kolkata",
  "Asia/Singapore",
  "Asia/Tokyo",
  "Australia/Sydney",
  "Pacific/Auckland",
] as const;

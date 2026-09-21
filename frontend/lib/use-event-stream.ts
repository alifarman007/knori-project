"use client";

import * as React from "react";

import { apiUrl } from "@/lib/api";
import { EVENTS_PATH } from "@/lib/endpoints";
import type { UserEvent } from "@/lib/types";

export type ConnectionState = "connecting" | "open" | "offline";

type Handler = (event: UserEvent) => void;

/** Reconnect backoff: quick twice, then slow, so a restart is invisible. */
const BACKOFF_MS = [1_000, 2_000, 5_000, 10_000, 30_000] as const;

const EVENT_NAMES: readonly UserEvent["event"][] = [
  "recognition.created",
  "recognition.withdrawn",
  "correction.effect.ready",
  "correction.effect.updated",
  "profile.updated",
  "heartbeat",
];

function parse(name: string, raw: string): UserEvent | null {
  if (!EVENT_NAMES.includes(name as UserEvent["event"])) return null;
  try {
    return { event: name, data: JSON.parse(raw) } as UserEvent;
  } catch {
    return null;
  }
}

/**
 * The per-user SSE channel (`GET /events`).
 *
 * One connection per tab: the handler is kept in a ref so a screen can pass an
 * inline arrow function without tearing the stream down on every render. The
 * browser's own EventSource retry is not enough here — the API restarts on every
 * deploy, so the backoff and the visible connection state are ours.
 */
export function useEventStream(onEvent: Handler, enabled = true): ConnectionState {
  const [state, setState] = React.useState<ConnectionState>("connecting");
  const handlerRef = React.useRef(onEvent);
  handlerRef.current = onEvent;

  React.useEffect(() => {
    if (!enabled || typeof window === "undefined" || typeof EventSource === "undefined") {
      return;
    }

    let source: EventSource | null = null;
    let retryTimer: number | null = null;
    let attempt = 0;
    let closed = false;

    function connect() {
      if (closed) return;
      setState(attempt === 0 ? "connecting" : "offline");
      source = new EventSource(apiUrl(EVENTS_PATH), { withCredentials: true });

      source.onopen = () => {
        attempt = 0;
        setState("open");
      };

      source.onerror = () => {
        source?.close();
        source = null;
        if (closed) return;
        setState("offline");
        const wait = BACKOFF_MS[Math.min(attempt, BACKOFF_MS.length - 1)] ?? 30_000;
        attempt += 1;
        retryTimer = window.setTimeout(connect, wait);
      };

      for (const name of EVENT_NAMES) {
        source.addEventListener(name, (event) => {
          const parsed = parse(name, (event as MessageEvent<string>).data);
          if (parsed) handlerRef.current(parsed);
        });
      }
    }

    connect();

    return () => {
      closed = true;
      if (retryTimer) window.clearTimeout(retryTimer);
      source?.close();
    };
  }, [enabled]);

  return state;
}

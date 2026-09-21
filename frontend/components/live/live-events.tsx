"use client";

import { useQueryClient } from "@tanstack/react-query";
import * as React from "react";

import { keys } from "@/lib/query-keys";
import type { UserEvent } from "@/lib/types";
import { useEventStream, type ConnectionState } from "@/lib/use-event-stream";

type Handler = (event: UserEvent) => void;

interface LiveContextValue {
  connection: ConnectionState;
  subscribe: (handler: Handler) => () => void;
}

const LiveContext = React.createContext<LiveContextValue | null>(null);

/**
 * One SSE connection for the whole signed-in app.
 *
 * Two jobs: keep the caches honest (a Recognition that arrived while you were
 * on Settings should already be there when you switch tabs), and let individual
 * screens react — the chat shows a chip, the inspect screen waits for its
 * "what changed" panel.
 */
export function LiveEventsProvider({ children }: { children: React.ReactNode }) {
  const queryClient = useQueryClient();
  const handlers = React.useRef(new Set<Handler>());

  const onEvent = React.useCallback(
    (event: UserEvent) => {
      switch (event.event) {
        case "recognition.created":
        case "recognition.withdrawn":
          void queryClient.invalidateQueries({ queryKey: ["recognitions"] });
          void queryClient.invalidateQueries({ queryKey: keys.recognitionSummary });
          break;
        case "correction.effect.ready":
        case "correction.effect.updated":
          void queryClient.invalidateQueries({
            queryKey: keys.correctionEffect(event.data.feedback_id),
          });
          void queryClient.invalidateQueries({ queryKey: ["recognitions"] });
          break;
        case "profile.updated":
          void queryClient.invalidateQueries({ queryKey: keys.memoryProfile });
          void queryClient.invalidateQueries({ queryKey: keys.memoryItems });
          break;
        default:
          break;
      }
      for (const handler of handlers.current) handler(event);
    },
    [queryClient],
  );

  const connection = useEventStream(onEvent);

  const value = React.useMemo<LiveContextValue>(
    () => ({
      connection,
      subscribe: (handler: Handler) => {
        handlers.current.add(handler);
        return () => {
          handlers.current.delete(handler);
        };
      },
    }),
    [connection],
  );

  return <LiveContext.Provider value={value}>{children}</LiveContext.Provider>;
}

function useLive(): LiveContextValue | null {
  return React.useContext(LiveContext);
}

/** Run `handler` for every event. Safe to pass an inline function. */
export function useLiveEvent(handler: Handler): void {
  const live = useLive();
  const handlerRef = React.useRef(handler);
  handlerRef.current = handler;

  React.useEffect(() => {
    if (!live) return;
    return live.subscribe((event) => handlerRef.current(event));
  }, [live]);
}

export function useConnection(): ConnectionState {
  return useLive()?.connection ?? "connecting";
}

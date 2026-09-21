"use client";

import { useQuery } from "@tanstack/react-query";

import { Skeleton } from "@/components/ui/skeleton";
import { formatDateTime } from "@/lib/format";
import { historyWords } from "@/lib/labels";
import { recognitions as api } from "@/lib/endpoints";
import { keys } from "@/lib/query-keys";
import type { Uuid } from "@/lib/types";
import { cn } from "@/lib/utils";

export interface HistoryTimelineProps {
  recognitionId: Uuid;
  className?: string;
}

/**
 * Everything that has happened to this card, oldest first.
 *
 * `recognition_events` is append-only, so this is the only screen where the
 * person can see that KnoRI changed its mind — and when, and because of what.
 */
export function HistoryTimeline({ recognitionId, className }: HistoryTimelineProps) {
  const query = useQuery({
    queryKey: keys.recognitionHistory(recognitionId),
    queryFn: () => api.history(recognitionId),
  });

  if (query.isPending) {
    return (
      <div className={cn("flex flex-col gap-3", className)} aria-busy="true">
        <Skeleton className="h-4 w-48" />
        <Skeleton className="h-4 w-40" />
      </div>
    );
  }

  if (query.isError || query.data.length === 0) {
    return (
      <p className={cn("text-sm text-ink-muted", className)}>
        {query.isError ? "The history could not be loaded." : "Nothing has happened to this yet."}
      </p>
    );
  }

  return (
    <ol className={cn("flex flex-col", className)}>
      {query.data.map((entry, index) => (
        <li key={entry.id} className="relative flex gap-4 pb-5 last:pb-0">
          <span aria-hidden="true" className="relative flex w-3 shrink-0 justify-center">
            <span
              className={cn(
                "mt-[7px] size-2 rounded-full",
                entry.actor === "user" ? "bg-accent" : "bg-line-strong",
              )}
            />
            {index < query.data.length - 1 ? (
              <span className="absolute top-4 h-full w-px bg-line" />
            ) : null}
          </span>
          <div className="min-w-0 flex-1">
            <p className="text-base text-ink">{entry.label || historyWords(entry.event)}</p>
            <time dateTime={entry.at} className="mt-0.5 block text-xs text-ink-muted">
              {formatDateTime(entry.at)}
            </time>
          </div>
        </li>
      ))}
    </ol>
  );
}

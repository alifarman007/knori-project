"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import * as React from "react";

import { ActionableCard } from "@/components/recognition/actionable-card";
import { Skeleton, SkeletonText } from "@/components/ui/skeleton";
import { recognitions as api } from "@/lib/endpoints";
import { keys } from "@/lib/query-keys";
import type { Uuid } from "@/lib/types";
import { cn } from "@/lib/utils";

export interface InlineRecognitionProps {
  recognitionId: Uuid;
  /** Anchor id so the chip and the deep link can scroll here. */
  anchorId?: string;
  className?: string;
}

/**
 * A Recognition card sitting inside the thread, where `conversation_events`
 * says it belongs — right after the message whose evidence tipped it over.
 *
 * It is fetched rather than pushed: the SSE event carries only an id, and the
 * card must never be rendered from anything but the server's own row.
 */
export function InlineRecognition({ recognitionId, anchorId, className }: InlineRecognitionProps) {
  const query = useQuery({
    queryKey: keys.recognition(recognitionId),
    queryFn: () => api.get(recognitionId),
  });

  // Reading it in the thread counts as having seen it.
  const seenRef = React.useRef<string | null>(null);
  React.useEffect(() => {
    if (!query.data || query.data.presented_at) return;
    if (seenRef.current === recognitionId) return;
    seenRef.current = recognitionId;
    void api.markSeen(recognitionId).catch(() => undefined);
  }, [query.data, recognitionId]);

  return (
    <section
      id={anchorId}
      aria-label="Something KnoRI noticed"
      className={cn("scroll-mt-24 py-2", className)}
    >
      <div className="mb-2.5 flex items-center gap-3">
        <span aria-hidden="true" className="h-px flex-1 bg-accent-line" />
        <span className="knori-eyebrow text-accent">KnoRI noticed something here</span>
        <span aria-hidden="true" className="h-px flex-1 bg-accent-line" />
      </div>

      {query.isPending ? (
        <div className="rounded-lg border border-line bg-surface p-5">
          <Skeleton className="h-4 w-24" />
          <Skeleton className="mt-3 h-6 w-2/3" />
          <SkeletonText lines={3} className="mt-3" />
        </div>
      ) : query.isError || !query.data ? (
        <p className="rounded-lg border border-dashed border-line-strong px-4 py-3 text-sm text-ink-muted">
          This Recognition could not be loaded.{" "}
          <Link href="/app/recognitions" className="underline underline-offset-4">
            Open the Recognitions tab
          </Link>
          .
        </p>
      ) : (
        <ActionableCard
          recognition={query.data}
          provenance={query.data.provenance}
          href={`/app/recognitions/${recognitionId}`}
        />
      )}
    </section>
  );
}

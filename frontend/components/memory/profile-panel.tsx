"use client";

import { useQuery } from "@tanstack/react-query";

import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { Skeleton, SkeletonText } from "@/components/ui/skeleton";
import { memory } from "@/lib/endpoints";
import { formatDate } from "@/lib/format";
import { keys } from "@/lib/query-keys";
import { cn } from "@/lib/utils";

const TRIGGER_WORDS: Record<string, string> = {
  onboarding: "after your first answers",
  correction: "after a correction you made",
  recognition: "after you accepted a Recognition",
  memory: "after something new was remembered",
  schedule: "on its regular pass over what it knows",
  manual: "because you asked for it",
};

/**
 * "How KnoRI sees you" — the profile the chat actually reasons with.
 *
 * It is shown verbatim, with its version and why it was last rewritten. There
 * is no hidden second version: what is on this page is what goes into the
 * model, which is the only way "you can see what it knows" means anything.
 */
export function ProfilePanel({ className }: { className?: string }) {
  const query = useQuery({ queryKey: keys.memoryProfile, queryFn: memory.profile });

  return (
    <Card tone="recognition" className={cn("overflow-hidden", className)}>
      <div className="px-5 py-5 sm:px-6 sm:py-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 className="font-serif text-lg text-ink">How KnoRI sees you</h2>
          {query.data ? (
            <Badge tone="outline" mono>
              version {query.data.version}
            </Badge>
          ) : null}
        </div>

        {query.isPending ? (
          <SkeletonText lines={4} className="mt-4" />
        ) : query.isError ? (
          <p className="mt-3 text-base text-ink-muted">
            KnoRI has not written this yet, or it could not be loaded.
          </p>
        ) : !query.data?.profile_text ? (
          <p className="mt-3 max-w-prose text-base text-ink-muted">
            Nothing written yet. KnoRI writes this once it has enough of your own words to describe
            you without guessing.
          </p>
        ) : (
          <p className="mt-4 whitespace-pre-wrap knori-prose">{query.data.profile_text}</p>
        )}

        {query.data?.created_at ? (
          <p className="mt-5 border-t border-line pt-4 text-sm text-ink-muted">
            Last rewritten {formatDate(query.data.created_at)}
            {query.data.trigger ? ` — ${TRIGGER_WORDS[query.data.trigger] ?? query.data.trigger}` : ""}
            .
          </p>
        ) : null}
      </div>
    </Card>
  );
}

/** A thin version for places that only need the skeleton shape. */
export function ProfileSkeleton() {
  return (
    <Card tone="recognition" className="px-5 py-5 sm:px-6 sm:py-6">
      <Skeleton className="h-5 w-40" />
      <SkeletonText lines={4} className="mt-4" />
    </Card>
  );
}

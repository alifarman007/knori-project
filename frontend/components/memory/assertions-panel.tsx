"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import * as React from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { SkeletonText } from "@/components/ui/skeleton";
import { useToast } from "@/components/ui/toast";
import { memory } from "@/lib/endpoints";
import { formatDate } from "@/lib/format";
import { ASSERTION_KIND_LABEL } from "@/lib/labels";
import { keys } from "@/lib/query-keys";
import type { Uuid } from "@/lib/types";
import { useErrorToast } from "@/lib/use-error-toast";
import { cn } from "@/lib/utils";

/**
 * "Your corrections" — every claim KnoRI has to respect because you said so.
 *
 * Retracting one is a real change, not a tidy-up: the engine stops weighting it
 * and the claim it blocked can come back. The wording says that out loud.
 */
export function AssertionsPanel({ className }: { className?: string }) {
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const reportError = useErrorToast();
  const [retracting, setRetracting] = React.useState<Uuid | null>(null);

  const query = useQuery({ queryKey: keys.assertions, queryFn: memory.assertions });

  const retract = useMutation({
    mutationFn: (id: Uuid) => memory.retractAssertion(id),
    onMutate: (id) => setRetracting(id),
    onSuccess: () => {
      toast({
        title: "Taken back",
        description: "KnoRI may raise the original claim again.",
        tone: "neutral",
      });
      void queryClient.invalidateQueries({ queryKey: keys.assertions });
      void queryClient.invalidateQueries({ queryKey: ["recognitions"] });
    },
    onError: (error) => reportError(error, "That could not be taken back"),
    onSettled: () => setRetracting(null),
  });

  const active = (query.data ?? []).filter((item) => item.status === "active");
  const retracted = (query.data ?? []).filter((item) => item.status !== "active");

  return (
    <section className={cn(className)} aria-labelledby="corrections">
      <h2 id="corrections" className="font-serif text-lg text-ink">
        Your corrections
      </h2>
      <p className="mt-1.5 max-w-prose text-base text-ink-muted">
        Each one is a claim KnoRI has to reason with from now on. They are written in the third
        person because that is the form the engine reads them in.
      </p>

      {query.isPending ? (
        <SkeletonText lines={3} className="mt-5" />
      ) : query.isError ? (
        <p className="mt-5 text-base text-ink-muted">These could not be loaded.</p>
      ) : active.length === 0 && retracted.length === 0 ? (
        <p className="mt-5 rounded-lg border border-dashed border-line-strong bg-sunken/60 px-5 py-6 text-base text-ink-muted">
          Nothing yet. When you correct a{" "}
          <Link href="/app/recognitions" className="underline underline-offset-4">
            Recognition
          </Link>
          , your words land here.
        </p>
      ) : (
        <ul className="mt-5 flex flex-col">
          {[...active, ...retracted].map((item) => {
            const isRetracted = item.status !== "active";
            return (
              <li
                key={item.id}
                className={cn(
                  "flex items-start gap-3 border-b border-line py-4 last:border-0",
                  isRetracted && "opacity-60",
                )}
              >
                <div className="min-w-0 flex-1">
                  <p
                    className={cn(
                      "font-serif text-md leading-relaxed text-ink",
                      isRetracted && "line-through decoration-line-strong",
                    )}
                  >
                    {item.statement}
                  </p>
                  <div className="mt-1.5 flex flex-wrap items-center gap-x-2 text-xs text-ink-muted">
                    <span className="knori-eyebrow">{ASSERTION_KIND_LABEL[item.kind]}</span>
                    <span aria-hidden="true">·</span>
                    <time dateTime={item.created_at}>{formatDate(item.created_at)}</time>
                    {item.topic ? (
                      <Badge tone="outline" mono>
                        {item.topic}
                      </Badge>
                    ) : null}
                  </div>
                </div>
                {!isRetracted ? (
                  <Button
                    size="sm"
                    variant="ghost"
                    loading={retracting === item.id}
                    onClick={() => retract.mutate(item.id)}
                  >
                    Take back
                  </Button>
                ) : null}
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

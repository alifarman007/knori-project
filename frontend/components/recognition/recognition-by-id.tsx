"use client";

import { useQuery } from "@tanstack/react-query";

import { ActionableCard } from "@/components/recognition/actionable-card";
import { Card } from "@/components/ui/card";
import { Skeleton, SkeletonText } from "@/components/ui/skeleton";
import { recognitions as api } from "@/lib/endpoints";
import { keys } from "@/lib/query-keys";
import type { Uuid } from "@/lib/types";

export interface RecognitionByIdProps {
  id: Uuid;
  /** Open the evidence straight away — used where the card is the answer. */
  defaultEvidenceOpen?: boolean;
  className?: string;
}

/** A full card fetched by id, for places that only receive an id over SSE. */
export function RecognitionById({ id, defaultEvidenceOpen, className }: RecognitionByIdProps) {
  const query = useQuery({ queryKey: keys.recognition(id), queryFn: () => api.get(id) });

  if (query.isPending) {
    return (
      <Card tone="recognition" className={className}>
        <div className="px-5 py-5">
          <Skeleton className="h-5 w-24" />
          <Skeleton className="mt-3 h-6 w-2/3" />
          <SkeletonText lines={2} className="mt-3" />
        </div>
      </Card>
    );
  }

  if (query.isError || !query.data) {
    return (
      <p className="text-sm text-ink-muted">That Recognition could not be loaded right now.</p>
    );
  }

  return (
    <ActionableCard
      recognition={query.data}
      provenance={query.data.provenance}
      defaultEvidenceOpen={defaultEvidenceOpen}
      href={`/app/recognitions/${id}`}
      className={className}
    />
  );
}

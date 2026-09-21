"use client";

import { useQuery } from "@tanstack/react-query";
import * as React from "react";

import { ActionableCard } from "@/components/recognition/actionable-card";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState, type EmptyStateProps } from "@/components/ui/empty-state";
import { Skeleton, SkeletonText } from "@/components/ui/skeleton";
import { recognitions as api } from "@/lib/endpoints";
import { keys } from "@/lib/query-keys";

export interface RecognitionListProps {
  /** The tab key, used as the query key so tabs cache independently. */
  tab: string;
  empty: EmptyStateProps;
}

function CardSkeleton() {
  return (
    <Card tone="recognition" className="px-5 py-5 sm:px-6 sm:py-6">
      <div className="flex gap-2">
        <Skeleton className="h-5 w-20 rounded-full" />
        <Skeleton className="h-5 w-14 rounded-full" />
      </div>
      <Skeleton className="mt-4 h-6 w-3/5" />
      <SkeletonText lines={3} className="mt-3" />
      <Skeleton className="mt-5 h-4 w-52" />
    </Card>
  );
}

export function RecognitionList({ tab, empty }: RecognitionListProps) {
  const query = useQuery({
    queryKey: keys.recognitions(tab),
    queryFn: () => api.list(tab),
  });

  if (query.isPending) {
    return (
      <div className="flex flex-col gap-5" aria-busy="true">
        <CardSkeleton />
        <CardSkeleton />
      </div>
    );
  }

  if (query.isError) {
    return (
      <Alert tone="danger" title="These could not be loaded">
        <Button variant="secondary" size="sm" className="mt-2" onClick={() => void query.refetch()}>
          Try again
        </Button>
      </Alert>
    );
  }

  const items = query.data?.items ?? [];
  if (items.length === 0) return <EmptyState {...empty} />;

  return (
    <div className="flex flex-col gap-5">
      {items.map((item) => (
        <ActionableCard
          key={item.id}
          recognition={item}
          href={`/app/recognitions/${item.id}`}
        />
      ))}
    </div>
  );
}

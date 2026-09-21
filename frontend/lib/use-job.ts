"use client";

import { useQuery } from "@tanstack/react-query";
import * as React from "react";

import { jobs } from "@/lib/endpoints";
import { keys } from "@/lib/query-keys";
import type { JobStatus, Uuid } from "@/lib/types";

const TERMINAL = new Set<JobStatus["status"]>(["done", "failed", "dead"]);

export interface JobWatch {
  status: JobStatus | null;
  running: boolean;
  finished: boolean;
  failed: boolean;
}

/**
 * Poll `GET /jobs/{id}` until it settles.
 *
 * Used by "What have you noticed?", which enqueues a slow-lane job and then has
 * nothing to show until the worker gets to it. Two seconds is slow enough not to
 * matter and fast enough that the button does not feel stuck.
 */
export function useJob(jobId: Uuid | null, onFinished?: (job: JobStatus) => void): JobWatch {
  const query = useQuery({
    queryKey: keys.job(jobId ?? "none"),
    queryFn: () => jobs.get(jobId as Uuid),
    enabled: Boolean(jobId),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status && TERMINAL.has(status) ? false : 2_000;
    },
  });

  const status = query.data ?? null;
  const settled = status !== null && TERMINAL.has(status.status);

  const finishedRef = React.useRef(onFinished);
  finishedRef.current = onFinished;
  const notifiedRef = React.useRef<string | null>(null);

  React.useEffect(() => {
    if (!settled || !status) return;
    if (notifiedRef.current === status.id) return;
    notifiedRef.current = status.id;
    finishedRef.current?.(status);
  }, [settled, status]);

  return {
    status,
    running: Boolean(jobId) && !settled,
    finished: settled && status?.status === "done",
    failed: settled && status?.status !== "done",
  };
}

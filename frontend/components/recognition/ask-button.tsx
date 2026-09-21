"use client";

import { useQueryClient } from "@tanstack/react-query";
import * as React from "react";

import { Button } from "@/components/ui/button";
import { useToast } from "@/components/ui/toast";
import { recognitions } from "@/lib/endpoints";
import { keys } from "@/lib/query-keys";
import type { Uuid } from "@/lib/types";
import { useErrorToast } from "@/lib/use-error-toast";
import { useJob } from "@/lib/use-job";

/**
 * "What have you noticed?"
 *
 * It enqueues a slow-lane job and polls it. The wording of the result matters:
 * finding nothing is the expected answer most of the time, and saying so plainly
 * is what keeps the button from feeling broken.
 */
export function AskButton({ className }: { className?: string }) {
  const [jobId, setJobId] = React.useState<Uuid | null>(null);
  const [starting, setStarting] = React.useState(false);
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const reportError = useErrorToast();

  const job = useJob(jobId, (finished) => {
    setJobId(null);
    void queryClient.invalidateQueries({ queryKey: ["recognitions"] });
    void queryClient.invalidateQueries({ queryKey: keys.recognitionSummary });

    if (finished.status !== "done") {
      toast({
        title: "That did not finish",
        description: "KnoRI could not look right now. Try again in a minute.",
        tone: "danger",
      });
      return;
    }

    const created = Number(finished.result?.["recognitions_created"] ?? 0);
    toast({
      title: created > 0 ? "KnoRI came back with something" : "Nothing to show yet",
      description:
        created > 0
          ? "It is in the New tab, with the quotes behind it."
          : "Nothing you have said yet clears the bar: two things, on two different days, at least twelve hours apart.",
      tone: created > 0 ? "accent" : "neutral",
    });
  });

  async function run() {
    setStarting(true);
    try {
      const { job_id } = await recognitions.run();
      setJobId(job_id);
    } catch (error) {
      reportError(error, "KnoRI could not start looking");
    } finally {
      setStarting(false);
    }
  }

  return (
    <Button
      variant="secondary"
      className={className}
      loading={starting || job.running}
      loadingText="Looking…"
      onClick={() => void run()}
    >
      What have you noticed?
    </Button>
  );
}

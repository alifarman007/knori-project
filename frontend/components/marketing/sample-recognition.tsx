"use client";

import * as React from "react";

import { RecognitionCard } from "@/components/recognition/recognition-card";
import { useToast } from "@/components/ui/toast";
import { SAMPLE_PROVENANCE, SAMPLE_RECOGNITION } from "@/lib/mock";
import type { FeedbackAction } from "@/lib/types";

const OUTCOME: Record<FeedbackAction, { title: string; description: string }> = {
  accept: {
    title: "Accepted",
    description:
      "KnoRI treats this as settled: it stops proposing it again, and the chat can refer to it from now on.",
  },
  correct: {
    title: "A correction opens here",
    description:
      "You write what is actually true. KnoRI stores your sentence, drops the evidence that no longer fits, and shows you what changed.",
  },
  reject: {
    title: "Rejected",
    description:
      "KnoRI records that this is not true and will not raise the same claim again unless you take the correction back.",
  },
  dismiss: {
    title: "Set aside",
    description: "No claim either way. This version will not come back; a later one might.",
  },
};

/**
 * The live sample on the landing page. The four actions do not call the API —
 * they explain, in the person's own terms, what each one would do.
 */
export function SampleRecognition() {
  const { toast } = useToast();

  return (
    <RecognitionCard
      recognition={SAMPLE_RECOGNITION}
      provenance={SAMPLE_PROVENANCE}
      defaultEvidenceOpen
      onAction={(action: FeedbackAction) => {
        toast({ ...OUTCOME[action], tone: action === "accept" ? "positive" : "accent" });
      }}
    />
  );
}

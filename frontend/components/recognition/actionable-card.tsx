"use client";

import * as React from "react";

import { chatDeepLink } from "@/components/recognition/evidence-quote";
import { CorrectionSheet } from "@/components/recognition/correction-sheet";
import { RecognitionCard } from "@/components/recognition/recognition-card";
import { useFeedback } from "@/components/recognition/use-feedback";
import type { FeedbackAction, ProvenanceItem, Recognition, Uuid } from "@/lib/types";

export interface ActionableCardProps {
  recognition: Recognition;
  provenance?: readonly ProvenanceItem[];
  defaultEvidenceOpen?: boolean;
  /** Link on the title. Omitted on the detail screen, which is already there. */
  href?: string;
  /** Told the feedback id so the screen can watch for the "what changed" panel. */
  onCorrectionQueued?: (feedbackId: Uuid) => void;
  className?: string;
}

/**
 * A card wired to the API: four actions, optimistic, with the correction sheet.
 *
 * `RecognitionCard` stays presentational so the landing page can render one
 * without a session; everything that writes lives here.
 */
export function ActionableCard({
  recognition,
  provenance,
  defaultEvidenceOpen = false,
  href,
  onCorrectionQueued,
  className,
}: ActionableCardProps) {
  const [correcting, setCorrecting] = React.useState(false);
  const feedback = useFeedback({
    onQueued: (feedbackId, input) => {
      if (input.action === "correct") onCorrectionQueued?.(feedbackId);
    },
  });

  function act(action: FeedbackAction) {
    if (action === "correct") {
      setCorrecting(true);
      return;
    }
    feedback.submit({ id: recognition.id, action });
  }

  return (
    <>
      <RecognitionCard
        recognition={recognition}
        provenance={provenance}
        defaultEvidenceOpen={defaultEvidenceOpen}
        href={href}
        hrefFor={chatDeepLink}
        onAction={act}
        pendingAction={feedback.pendingFor(recognition.id)}
        className={className}
      />
      <CorrectionSheet
        open={correcting}
        onClose={() => setCorrecting(false)}
        title={recognition.title}
        submitting={feedback.isPending}
        onSubmit={(input) => {
          void feedback
            .submitAsync({ id: recognition.id, action: "correct", ...input })
            .then(() => setCorrecting(false))
            // Leave the sheet open on failure: their words are still in the box.
            .catch(() => undefined);
        }}
      />
    </>
  );
}

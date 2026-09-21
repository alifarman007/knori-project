"use client";

import * as React from "react";

import { RecognitionCard } from "@/components/recognition/recognition-card";
import { chatDeepLink } from "@/components/recognition/evidence-quote";
import { useToast } from "@/components/ui/toast";
import type { FeedbackAction, ProvenanceItem, Recognition } from "@/lib/types";

export interface RecognitionFeedProps {
  items: readonly Recognition[];
  /** Recognition id -> its evidence. Missing ids simply show the count line. */
  provenance?: Record<string, ProvenanceItem[]>;
  defaultEvidenceOpen?: boolean;
}

const ACKNOWLEDGEMENT: Record<FeedbackAction, string> = {
  accept: "Noted — KnoRI will treat this as settled.",
  correct: "Tell KnoRI what is actually true.",
  reject: "Noted — this claim will not come back.",
  dismiss: "Set aside for now.",
};

/**
 * A list of cards with their feedback wired to a toast.
 *
 * When `POST /recognitions/{id}/feedback` lands, this is where the optimistic
 * update and the TanStack mutation go; the card itself stays presentational.
 */
export function RecognitionFeed({
  items,
  provenance,
  defaultEvidenceOpen = false,
}: RecognitionFeedProps) {
  const { toast } = useToast();
  const [pending, setPending] = React.useState<{ id: string; action: FeedbackAction } | null>(null);

  function act(id: string, action: FeedbackAction) {
    setPending({ id, action });
    window.setTimeout(() => {
      setPending(null);
      toast({
        title: ACKNOWLEDGEMENT[action],
        description: "Not saved yet — the feedback endpoint is still being built.",
        tone: action === "accept" ? "positive" : "accent",
      });
    }, 600);
  }

  return (
    <div className="flex flex-col gap-5">
      {items.map((item) => (
        <RecognitionCard
          key={item.id}
          recognition={item}
          provenance={provenance?.[item.id]}
          defaultEvidenceOpen={defaultEvidenceOpen}
          href={`/app/recognitions/${item.id}`}
          hrefFor={chatDeepLink}
          pendingAction={pending?.id === item.id ? pending.action : null}
          onAction={(action) => act(item.id, action)}
        />
      ))}
    </div>
  );
}

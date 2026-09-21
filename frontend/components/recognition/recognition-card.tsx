"use client";

import Link from "next/link";
import * as React from "react";

import { IconChevronDown } from "@/components/icons";
import { ConfidenceBadge } from "@/components/recognition/confidence-badge";
import { EvidenceQuote } from "@/components/recognition/evidence-quote";
import { FeedbackBar } from "@/components/recognition/feedback-bar";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { evidenceSummary, KIND_LABEL, STATE_LABEL, summariseProvenance } from "@/lib/format";
import type { FeedbackAction, ProvenanceItem, Recognition } from "@/lib/types";
import { cn } from "@/lib/utils";

export interface RecognitionCardProps {
  recognition: Recognition;
  /** Supporting quotes. Without them the evidence section is not rendered. */
  provenance?: readonly ProvenanceItem[];
  /** Open the evidence on first render — the detail page and the demo do this. */
  defaultEvidenceOpen?: boolean;
  onAction?: (action: FeedbackAction) => void;
  pendingAction?: FeedbackAction | null;
  /** Link on the title, to `/app/recognitions/{id}`. */
  href?: string;
  hrefFor?: (item: ProvenanceItem) => string | null;
  /** Hides the four actions, e.g. on the landing page sample. */
  readOnly?: boolean;
  className?: string;
}

/**
 * The card a person sees when KnoRI has noticed something.
 *
 * Everything KnoRI claims is in the serif face; everything the product says
 * about itself (counts, labels, buttons) is in the sans. That split is the
 * whole design: a Recognition should read like a sentence somebody wrote about
 * you, not like a notification.
 */
export function RecognitionCard({
  recognition,
  provenance,
  defaultEvidenceOpen = false,
  onAction,
  pendingAction = null,
  href,
  hrefFor,
  readOnly = false,
  className,
}: RecognitionCardProps) {
  const [evidenceOpen, setEvidenceOpen] = React.useState(defaultEvidenceOpen);
  const reactId = React.useId();
  const evidenceId = `ev${reactId.replace(/:/g, "")}`;

  // On the list there is no evidence array — the API sends the counts with the
  // confidence instead, so the line reads the same in both places.
  const counts = provenance
    ? summariseProvenance(provenance)
    : {
        thingCount: recognition.confidence.supports,
        dayCount: recognition.confidence.distinct_days,
      };
  const summaryLine = evidenceSummary(counts.thingCount, counts.dayCount);

  const isNew =
    (recognition.state === "pending" || recognition.state === "presented") && !recognition.presented_at;

  return (
    <Card
      as="article"
      tone="recognition"
      aria-labelledby={`${evidenceId}-title`}
      className={cn("overflow-hidden", className)}
    >
      <div className="flex flex-col gap-4 px-5 py-5 sm:px-6 sm:py-6">
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone="accent" mono>
            {KIND_LABEL[recognition.kind]}
          </Badge>
          {isNew ? (
            <Badge tone="outline" mono dot>
              new
            </Badge>
          ) : recognition.state !== "presented" && recognition.state !== "pending" ? (
            <Badge tone={recognition.state === "accepted" ? "positive" : "neutral"} mono>
              {STATE_LABEL[recognition.state]}
            </Badge>
          ) : null}
          <ConfidenceBadge label={recognition.confidence.label} className="ml-auto" />
        </div>

        <div>
          <h3 id={`${evidenceId}-title`} className="font-serif text-xl leading-snug text-ink">
            {href ? (
              <Link
                href={href}
                className="rounded-sm decoration-accent-line underline-offset-4 hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus"
              >
                {recognition.title}
              </Link>
            ) : (
              recognition.title
            )}
          </h3>
          <p className="mt-2.5 font-serif text-md leading-relaxed text-ink-secondary">
            {recognition.body}
          </p>
        </div>

        {provenance && provenance.length > 0 ? (
          <div className="border-t border-line pt-4">
            <button
              type="button"
              aria-expanded={evidenceOpen}
              aria-controls={evidenceId}
              onClick={() => setEvidenceOpen((open) => !open)}
              className={cn(
                "group flex w-full items-center gap-2 text-left text-sm text-ink-muted",
                "rounded-sm transition-colors hover:text-ink",
                "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus",
              )}
            >
              <IconChevronDown
                className={cn(
                  "size-4 shrink-0 transition-transform duration-200",
                  evidenceOpen && "rotate-180",
                )}
              />
              <span>{summaryLine}</span>
              <span className="ml-auto shrink-0 underline decoration-line-strong underline-offset-4 group-hover:decoration-ink-muted">
                {evidenceOpen ? "hide" : "show me"}
              </span>
            </button>

            <ul
              id={evidenceId}
              hidden={!evidenceOpen}
              className="mt-4 flex flex-col gap-4 motion-safe:animate-fade"
            >
              {[...provenance]
                .sort((a, b) => a.display_order - b.display_order)
                .map((item) => (
                  <EvidenceQuote key={item.id} item={item} hrefFor={hrefFor} />
                ))}
            </ul>
          </div>
        ) : (
          <p className="text-sm text-ink-muted">{summaryLine}</p>
        )}
      </div>

      {!readOnly && onAction ? (
        <div className="border-t border-line bg-sunken/50 px-5 py-3.5 sm:px-6">
          <FeedbackBar
            state={recognition.state}
            onAction={onAction}
            pending={pendingAction}
            resolvedAt={recognition.resolved_at}
          />
        </div>
      ) : null}
    </Card>
  );
}

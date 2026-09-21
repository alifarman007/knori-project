"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import * as React from "react";

import { IconArrowLeft, IconHistory } from "@/components/icons";
import { ConfidenceBadge } from "@/components/recognition/confidence-badge";
import { CorrectionEffectPanel } from "@/components/recognition/correction-effect-panel";
import { CorrectionSheet } from "@/components/recognition/correction-sheet";
import { EvidenceList } from "@/components/recognition/evidence-list";
import { FeedbackBar } from "@/components/recognition/feedback-bar";
import { HistoryTimeline } from "@/components/recognition/history-timeline";
import { useFeedback } from "@/components/recognition/use-feedback";
import { PageShell } from "@/components/shell/page-header";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { Skeleton, SkeletonText } from "@/components/ui/skeleton";
import { recognitions as api } from "@/lib/endpoints";
import { evidenceSummary, KIND_LABEL, STATE_LABEL, summariseProvenance } from "@/lib/format";
import { keys } from "@/lib/query-keys";
import type { FeedbackAction, Uuid } from "@/lib/types";
import { cn } from "@/lib/utils";

function Loading() {
  return (
    <PageShell>
      <div className="pt-8" aria-busy="true">
        <Skeleton className="h-4 w-28" />
        <Skeleton className="mt-6 h-9 w-4/5" />
        <SkeletonText lines={3} className="mt-5" />
        <Skeleton className="mt-10 h-44 w-full rounded-lg" />
      </div>
    </PageShell>
  );
}

export function InspectScreen({ recognitionId }: { recognitionId: Uuid }) {
  const [correcting, setCorrecting] = React.useState(false);
  const [watching, setWatching] = React.useState<Uuid | null>(null);

  const query = useQuery({
    queryKey: keys.recognition(recognitionId),
    queryFn: () => api.get(recognitionId),
  });

  const feedback = useFeedback({
    onQueued: (feedbackId, input) => {
      if (input.action === "correct") setWatching(feedbackId);
    },
  });

  // Opening the inspect screen is the moment it counts as read.
  const seenRef = React.useRef<string | null>(null);
  React.useEffect(() => {
    if (!query.data || query.data.presented_at || seenRef.current === recognitionId) return;
    seenRef.current = recognitionId;
    void api.markSeen(recognitionId).catch(() => undefined);
  }, [query.data, recognitionId]);

  if (query.isPending) return <Loading />;

  if (query.isError || !query.data) {
    return (
      <PageShell>
        <div className="pt-10">
          <Alert tone="danger" title="This Recognition is not available">
            It may have been withdrawn, or it belongs to another account.
          </Alert>
          <Link
            href="/app/recognitions"
            className="mt-6 inline-flex items-center gap-1.5 text-base text-accent underline underline-offset-4"
          >
            <IconArrowLeft className="size-4" />
            Back to Recognitions
          </Link>
        </div>
      </PageShell>
    );
  }

  const card = query.data;
  const counts = summariseProvenance(card.provenance);
  const effectId = watching ?? card.correction_effect?.feedback_id ?? null;

  function act(action: FeedbackAction) {
    if (action === "correct") {
      setCorrecting(true);
      return;
    }
    feedback.submit({ id: card.id, action });
  }

  return (
    <PageShell className="pb-16">
      <Link
        href="/app/recognitions"
        className={cn(
          "mt-6 inline-flex items-center gap-1.5 rounded-sm text-sm text-ink-muted",
          "transition-colors hover:text-ink",
          "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus",
        )}
      >
        <IconArrowLeft className="size-4" />
        All Recognitions
      </Link>

      <header className="mt-5">
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone="accent" mono>
            {KIND_LABEL[card.kind]}
          </Badge>
          {card.state !== "presented" && card.state !== "pending" ? (
            <Badge tone={card.state === "accepted" ? "positive" : "neutral"} mono>
              {STATE_LABEL[card.state]}
            </Badge>
          ) : null}
          <ConfidenceBadge label={card.confidence.label} />
        </div>

        <h1 className="mt-4 text-2xl leading-tight">{card.title}</h1>
        <p className="mt-4 knori-prose">{card.body}</p>
        <p className="mt-4 text-sm text-ink-muted">
          {evidenceSummary(counts.thingCount, counts.dayCount)}
        </p>
      </header>

      <Card tone="sunken" className="mt-8 px-5 py-5 sm:px-6">
        <h2 className="font-serif text-lg text-ink">Why KnoRI thinks this</h2>
        <p className="mt-2.5 knori-prose text-base">{card.explanation}</p>
        <p className="mt-4 border-t border-line pt-4 text-sm leading-relaxed text-ink-muted">
          {card.confidence_in_words}
        </p>
      </Card>

      <section className="mt-10" aria-labelledby="evidence">
        <h2 id="evidence" className="font-serif text-lg text-ink">
          In your own words
        </h2>
        <p className="mt-1.5 max-w-prose text-base text-ink-muted">
          Each of these is exactly what you typed, with the day you typed it. Open any of them in
          the conversation it came from.
        </p>
        <EvidenceList items={card.provenance} className="mt-6" />
      </section>

      <section className="mt-10 border-t border-line pt-6" aria-labelledby="answer">
        <h2 id="answer" className="font-serif text-lg text-ink">
          Is this right?
        </h2>
        <p className="mt-1.5 max-w-prose text-base text-ink-muted">
          Whatever you answer is kept. Correcting it changes what KnoRI reasons with next time —
          it does not just hide the card.
        </p>
        <FeedbackBar
          className="mt-4"
          state={card.state}
          onAction={act}
          pending={feedback.pendingFor(card.id)}
          resolvedAt={card.resolved_at}
        />
        {card.feedback?.correction_text ? (
          <figure className="mt-5 border-l-2 border-accent-line pl-4">
            <figcaption className="knori-eyebrow">You said</figcaption>
            <blockquote className="mt-1.5 font-serif text-md leading-relaxed text-ink">
              {card.feedback.correction_text}
            </blockquote>
          </figure>
        ) : null}
      </section>

      {effectId ? <CorrectionEffectPanel feedbackId={effectId} className="mt-8" /> : null}

      <section className="mt-10 border-t border-line pt-6" aria-labelledby="history">
        <h2 id="history" className="flex items-center gap-2 font-serif text-lg text-ink">
          <IconHistory className="size-4 text-ink-muted" />
          History
        </h2>
        <HistoryTimeline recognitionId={card.id} className="mt-5" />
      </section>

      <details className="mt-10 border-t border-line pt-6">
        <summary
          className={cn(
            "cursor-pointer list-none text-sm text-ink-muted transition-colors hover:text-ink",
            "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus",
          )}
        >
          Technical details
        </summary>
        <dl className="mt-4 grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 font-mono text-xs text-ink-muted">
          <dt>interpretation</dt>
          <dd className="break-all">
            {card.interpretation.id} · v{card.interpretation.version}
          </dd>
          <dt>topic</dt>
          <dd>{card.interpretation.topic}</dd>
          <dt>claim</dt>
          <dd className="break-words">{card.interpretation.statement}</dd>
          <dt>confidence</dt>
          <dd>{card.confidence.value.toFixed(2)} (conf-v1)</dd>
          <dt>card</dt>
          <dd className="break-all">{card.id}</dd>
        </dl>
      </details>

      <CorrectionSheet
        open={correcting}
        onClose={() => setCorrecting(false)}
        title={card.title}
        submitting={feedback.isPending}
        onSubmit={(input) => {
          void feedback
            .submitAsync({ id: card.id, action: "correct", ...input })
            .then(() => setCorrecting(false))
            .catch(() => undefined);
        }}
      />
    </PageShell>
  );
}

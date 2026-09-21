"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import * as React from "react";

import { RecognitionById } from "@/components/recognition/recognition-by-id";
import { Card } from "@/components/ui/card";
import { Spinner } from "@/components/ui/spinner";
import { memory as memoryApi, recognitions as api } from "@/lib/endpoints";
import { keys } from "@/lib/query-keys";
import { pluralise } from "@/lib/format";
import type { CorrectionEffect, Uuid } from "@/lib/types";
import { cn } from "@/lib/utils";

export interface CorrectionEffectPanelProps {
  feedbackId: Uuid;
  className?: string;
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="border-t border-line pt-4 first:border-0 first:pt-0">
      <p className="knori-eyebrow">{label}</p>
      <div className="mt-2">{children}</div>
    </div>
  );
}

/**
 * What the correction actually changed.
 *
 * This panel is the difference between a product that listens and one that only
 * lets you complain. It shows the claim KnoRI now has to respect, the cards it
 * pulled because of it, and the before/after of the profile the chat reasons
 * with — all from `correction_effects`, not from anything the client inferred.
 */
export function CorrectionEffectPanel({ feedbackId, className }: CorrectionEffectPanelProps) {
  const query = useQuery({
    queryKey: keys.correctionEffect(feedbackId),
    queryFn: () => api.effect(feedbackId),
    // The job usually lands within seconds; SSE also invalidates this key.
    refetchInterval: (query) => (query.state.data?.status === "ready" ? false : 3_000),
  });

  const effect: CorrectionEffect | undefined = query.data;

  const assertions = useQuery({
    queryKey: keys.assertions,
    queryFn: memoryApi.assertions,
    enabled: Boolean(effect?.assertions_created?.length),
  });

  if (query.isError) {
    return (
      <Card tone="sunken" className={cn("px-5 py-4", className)}>
        <p className="text-sm text-ink-muted">
          KnoRI saved your correction, but what it changed could not be loaded. It is on{" "}
          <Link href="/app/memory" className="underline underline-offset-4">
            your memory page
          </Link>
          .
        </p>
      </Card>
    );
  }

  if (!effect || effect.status === "pending") {
    return (
      <Card tone="sunken" className={cn("flex items-center gap-3 px-5 py-4", className)}>
        <Spinner label={null} className="text-accent" />
        <p className="text-base text-ink-secondary">
          Your correction is saved. KnoRI is working out what it changes — this usually takes a few
          seconds.
        </p>
      </Card>
    );
  }

  const created = effect.recognitions_created ?? [];
  const withdrawn = effect.recognitions_withdrawn ?? [];
  const recorded = (assertions.data ?? []).filter((item) =>
    effect.assertions_created?.includes(item.id),
  );

  return (
    <Card tone="recognition" className={cn("overflow-hidden", className)}>
      <div className="flex flex-col gap-4 px-5 py-5 sm:px-6 sm:py-6">
        <h2 className="font-serif text-lg text-ink">What your correction changed</h2>

        {effect.summary ? (
          <p className="font-serif text-md leading-relaxed text-ink-secondary">{effect.summary}</p>
        ) : null}

        {recorded.length > 0 ? (
          <Row label="KnoRI now takes this as given">
            <ul className="flex flex-col gap-2">
              {recorded.map((item) => (
                <li
                  key={item.id}
                  className="border-l-2 border-accent-line pl-3 font-serif text-md text-ink"
                >
                  {item.statement}
                </li>
              ))}
            </ul>
          </Row>
        ) : null}

        {withdrawn.length > 0 ? (
          <Row label="Withdrawn">
            <p className="text-base text-ink-secondary">
              {withdrawn.length} {pluralise(withdrawn.length, "card")} built on the old reading{" "}
              {withdrawn.length === 1 ? "was" : "were"} pulled.{" "}
              <Link
                href="/app/recognitions"
                className="text-accent underline decoration-accent-line underline-offset-4"
              >
                See them
              </Link>
            </p>
          </Row>
        ) : null}

        {effect.effects?.length ? (
          <Row label="Re-scored">
            <ul className="flex flex-col gap-2 text-base text-ink-secondary">
              {effect.effects.map((item) => (
                <li key={item.interpretation_id} className="flex flex-wrap items-baseline gap-x-2">
                  <span className="min-w-0 flex-1 font-serif text-ink">{item.statement}</span>
                  <span className="font-mono text-2xs uppercase tracking-[0.12em] text-ink-muted">
                    {item.before.status} → {item.after.status}
                  </span>
                </li>
              ))}
            </ul>
          </Row>
        ) : null}

        {effect.profile_before_text || effect.profile_after_text ? (
          <Row label="How KnoRI describes you">
            <div className="grid gap-3 sm:grid-cols-2">
              <div className="rounded-md border border-line bg-sunken px-3.5 py-3">
                <p className="knori-eyebrow">Before</p>
                <p className="mt-1.5 whitespace-pre-wrap font-serif text-base leading-relaxed text-ink-muted">
                  {effect.profile_before_text ?? "Nothing written yet."}
                </p>
              </div>
              <div className="rounded-md border border-accent-line bg-accent-soft/60 px-3.5 py-3">
                <p className="knori-eyebrow text-accent">After</p>
                <p className="mt-1.5 whitespace-pre-wrap font-serif text-base leading-relaxed text-ink">
                  {effect.profile_after_text ?? "Unchanged."}
                </p>
              </div>
            </div>
          </Row>
        ) : null}

        {created.length > 0 ? (
          <Row label="What KnoRI says instead">
            <div className="flex flex-col gap-4">
              {created.map((id) => (
                <RecognitionById key={id} id={id} defaultEvidenceOpen />
              ))}
            </div>
          </Row>
        ) : null}
      </div>
    </Card>
  );
}

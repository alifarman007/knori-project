"use client";

import Link from "next/link";
import * as React from "react";

import { IconClose } from "@/components/icons";
import { pluralise } from "@/lib/format";
import type { WelcomeBack } from "@/lib/types";
import { cn } from "@/lib/utils";

export interface WelcomeBackStripProps {
  welcome: WelcomeBack;
  className?: string;
}

function daysAway(days: number): string {
  if (days <= 0) return "Back already";
  if (days === 1) return "A day away";
  if (days < 7) return `${days} days away`;
  if (days < 14) return "A week away";
  return `${Math.round(days / 7)} weeks away`;
}

/**
 * What happened while they were gone — shown once, at the top of the thread.
 *
 * It is a strip and not a card because it is not news about them, only about
 * the product. Anything KnoRI noticed about the person gets a Recognition card
 * with its evidence, never a summary line.
 */
export function WelcomeBackStrip({ welcome, className }: WelcomeBackStripProps) {
  const [dismissed, setDismissed] = React.useState(false);
  if (dismissed) return null;

  const nothing =
    welcome.memories_added === 0 && welcome.new_recognitions === 0 && welcome.days_away <= 0;
  if (nothing) return null;

  return (
    <aside
      className={cn(
        "flex items-start gap-3 rounded-lg border border-line bg-sunken/70 px-4 py-3",
        className,
      )}
    >
      <div className="min-w-0 flex-1">
        <p className="knori-eyebrow">{daysAway(welcome.days_away)}</p>
        <p className="mt-1.5 text-base text-ink-secondary">
          {welcome.memories_added > 0 ? (
            <>
              {welcome.memories_added} new {pluralise(welcome.memories_added, "thing")} remembered
            </>
          ) : (
            "Nothing new was remembered"
          )}
          {welcome.new_recognitions > 0 ? (
            <>
              {" · "}
              <Link
                href="/app/recognitions"
                className="text-accent underline decoration-accent-line underline-offset-4 hover:text-accent-hover"
              >
                {welcome.new_recognitions}{" "}
                {pluralise(welcome.new_recognitions, "Recognition")} waiting
              </Link>
            </>
          ) : null}
        </p>
      </div>
      <button
        type="button"
        onClick={() => setDismissed(true)}
        aria-label="Hide this"
        className={cn(
          "-mr-1 grid size-7 shrink-0 place-items-center rounded-sm text-ink-muted",
          "transition-colors hover:bg-surface hover:text-ink",
          "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus",
        )}
      >
        <IconClose className="size-3.5" />
      </button>
    </aside>
  );
}

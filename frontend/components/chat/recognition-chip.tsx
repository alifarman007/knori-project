"use client";

import * as React from "react";

import { IconArrowRight, IconClose } from "@/components/icons";
import { cn } from "@/lib/utils";

export interface RecognitionChipProps {
  /** Scroll the inline card into view. */
  onOpen: () => void;
  onDismiss: () => void;
  className?: string;
}

/**
 * The one interruption KnoRI is allowed.
 *
 * When `recognition.created` arrives over SSE while the person is mid-thread,
 * the card itself is placed further down, where the evidence came from. This
 * chip says it exists and offers to take them there — it never states the
 * claim, because a claim without its evidence is exactly what this product is
 * not.
 */
export function RecognitionChip({ onOpen, onDismiss, className }: RecognitionChipProps) {
  return (
    <div
      role="status"
      className={cn(
        "pointer-events-auto flex items-center gap-2 rounded-full border border-accent-line",
        "bg-accent-soft py-1.5 pl-4 pr-1.5 shadow-lift motion-safe:animate-rise",
        className,
      )}
    >
      <span aria-hidden="true" className="size-1.5 shrink-0 rounded-full bg-accent" />
      <span className="text-sm text-ink">KnoRI noticed something</span>
      <button
        type="button"
        onClick={onOpen}
        className={cn(
          "inline-flex items-center gap-1 rounded-full bg-accent px-3 py-1 text-sm font-medium",
          "text-accent-ink transition-colors hover:bg-accent-hover",
          "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus",
        )}
      >
        Read it
        <IconArrowRight className="size-3.5" />
      </button>
      <button
        type="button"
        onClick={onDismiss}
        aria-label="Not now"
        className={cn(
          "grid size-7 shrink-0 place-items-center rounded-full text-ink-muted",
          "transition-colors hover:bg-surface hover:text-ink",
          "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus",
        )}
      >
        <IconClose className="size-3.5" />
      </button>
    </div>
  );
}

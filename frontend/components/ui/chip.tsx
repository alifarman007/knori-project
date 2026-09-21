"use client";

import * as React from "react";

import { cn } from "@/lib/utils";

export interface ChipProps extends Omit<React.ButtonHTMLAttributes<HTMLButtonElement>, "onSelect"> {
  selected: boolean;
  /** A line under the label inside the chip, for a short "what this means". */
  hint?: string;
}

/**
 * A single-choice chip, used for the reason on a correction.
 *
 * It is a real toggle button (`aria-pressed`), not a styled radio, because the
 * choice is optional: a person may correct a card without naming a category,
 * and a radio group with no empty option would make that impossible.
 */
export const Chip = React.forwardRef<HTMLButtonElement, ChipProps>(function Chip(
  { selected, hint, className, children, ...props },
  ref,
) {
  return (
    <button
      ref={ref}
      type="button"
      aria-pressed={selected}
      className={cn(
        "flex flex-col items-start gap-0.5 rounded-md border px-3 py-2 text-left transition-colors",
        "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus",
        selected
          ? "border-accent bg-accent-soft text-ink"
          : "border-line-strong bg-surface text-ink-secondary hover:border-ink-muted/60 hover:text-ink",
        className,
      )}
      {...props}
    >
      <span className="text-base font-medium">{children}</span>
      {hint ? <span className="text-xs text-ink-muted">{hint}</span> : null}
    </button>
  );
});

export interface SegmentedProps<T extends string> {
  value: T;
  onChange: (value: T) => void;
  options: readonly { value: T; label: string }[];
  "aria-label": string;
  className?: string;
}

/** Two or three mutually exclusive options, e.g. how KnoRI should talk. */
export function Segmented<T extends string>({
  value,
  onChange,
  options,
  className,
  ...props
}: SegmentedProps<T>) {
  return (
    <div
      role="radiogroup"
      className={cn("inline-flex rounded-md border border-line-strong bg-sunken p-0.5", className)}
      {...props}
    >
      {options.map((option) => {
        const selected = option.value === value;
        return (
          <button
            key={option.value}
            type="button"
            role="radio"
            aria-checked={selected}
            onClick={() => onChange(option.value)}
            className={cn(
              "rounded-[7px] px-3 py-1.5 text-sm font-medium transition-colors",
              "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus",
              selected
                ? "bg-surface text-ink shadow-soft"
                : "text-ink-muted hover:text-ink-secondary",
            )}
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}

import * as React from "react";

import { cn } from "@/lib/utils";

export type BadgeTone = "neutral" | "accent" | "positive" | "danger" | "info" | "outline";

const TONES: Record<BadgeTone, string> = {
  neutral: "bg-sunken text-ink-secondary border-line",
  accent: "bg-accent-soft text-accent border-accent-line",
  positive: "bg-positive-soft text-positive border-positive/30",
  danger: "bg-danger-soft text-danger border-danger/30",
  info: "bg-info-soft text-info border-info/30",
  outline: "bg-transparent text-ink-muted border-line-strong",
};

export interface BadgeProps extends React.HTMLAttributes<HTMLSpanElement> {
  tone?: BadgeTone;
  /** Mono + letterspaced, for kind tags and dates. */
  mono?: boolean;
  dot?: boolean;
}

export function Badge({ tone = "neutral", mono = false, dot = false, className, children, ...props }: BadgeProps) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-medium",
        mono && "font-mono text-2xs uppercase tracking-[0.12em]",
        TONES[tone],
        className,
      )}
      {...props}
    >
      {dot ? <span aria-hidden="true" className="size-1.5 rounded-full bg-current" /> : null}
      {children}
    </span>
  );
}

export interface CountBadgeProps {
  count: number;
  max?: number;
  className?: string;
  /** Read out in full, e.g. "3 new Recognitions". */
  label: string;
}

/** The small number on the Recognitions nav item. */
export function CountBadge({ count, max = 9, className, label }: CountBadgeProps) {
  if (count <= 0) return null;
  return (
    <span
      className={cn(
        "inline-flex min-w-[1.25rem] items-center justify-center rounded-full bg-accent px-1.5",
        "font-mono text-2xs font-semibold leading-5 text-accent-ink tabular-nums",
        className,
      )}
    >
      <span aria-hidden="true">{count > max ? `${max}+` : count}</span>
      <span className="sr-only">{label}</span>
    </span>
  );
}

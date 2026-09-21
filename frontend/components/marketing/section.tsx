import * as React from "react";

import { cn } from "@/lib/utils";

export type SectionSpacing = "default" | "tight" | "none";

/**
 * Vertical rhythm is a prop rather than a class override: a caller passing
 * `py-0` would still be beaten by the responsive `sm:py-24` in the base, and
 * that bug is invisible until someone looks at a wide screen.
 */
const SPACING: Record<SectionSpacing, string> = {
  default: "py-20 sm:py-24",
  tight: "py-12 sm:py-14",
  none: "py-0",
};

export interface SectionProps extends React.HTMLAttributes<HTMLElement> {
  spacing?: SectionSpacing;
}

export function Section({ spacing = "default", className, children, ...props }: SectionProps) {
  return (
    <section
      className={cn("knori-gutter mx-auto w-full max-w-6xl", SPACING[spacing], className)}
      {...props}
    >
      {children}
    </section>
  );
}

export interface SectionHeadingProps {
  /** The small mono line above the heading: a number, or two or three words. */
  eyebrow?: string;
  title: React.ReactNode;
  lede?: React.ReactNode;
  className?: string;
  align?: "left" | "center";
}

export function SectionHeading({
  eyebrow,
  title,
  lede,
  className,
  align = "left",
}: SectionHeadingProps) {
  return (
    <div className={cn("max-w-2xl", align === "center" && "mx-auto text-center", className)}>
      {eyebrow ? <p className="knori-eyebrow">{eyebrow}</p> : null}
      <h2 className={cn("text-2xl sm:text-3xl", eyebrow && "mt-3")}>{title}</h2>
      {lede ? <p className="knori-prose mt-4">{lede}</p> : null}
    </div>
  );
}

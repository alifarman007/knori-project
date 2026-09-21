import * as React from "react";

import { cn } from "@/lib/utils";

export type CardTone = "default" | "sunken" | "recognition";

const TONES: Record<CardTone, string> = {
  default: "bg-surface border-line shadow-soft",
  sunken: "bg-sunken border-line shadow-none",
  // The only place the accent becomes structural: a marked page edge.
  recognition: "bg-surface border-line shadow-lift border-l-2 border-l-accent",
};

export interface CardProps extends React.HTMLAttributes<HTMLElement> {
  tone?: CardTone;
  /** The element to render. A list of cards should be `li` inside a `ul`. */
  as?: "div" | "article" | "section" | "li";
}

export function Card({ tone = "default", as = "div", className, ...props }: CardProps) {
  const Tag = as as React.ElementType;
  return <Tag className={cn("rounded-lg border", TONES[tone], className)} {...props} />;
}

export function CardHeader({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("flex flex-col gap-2 px-5 pt-5 sm:px-6 sm:pt-6", className)} {...props} />;
}

export function CardTitle({ className, ...props }: React.HTMLAttributes<HTMLHeadingElement>) {
  return <h3 className={cn("font-serif text-lg text-ink", className)} {...props} />;
}

export function CardDescription({ className, ...props }: React.HTMLAttributes<HTMLParagraphElement>) {
  return <p className={cn("text-sm text-ink-muted", className)} {...props} />;
}

export function CardBody({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("px-5 py-4 sm:px-6 sm:py-5", className)} {...props} />;
}

export function CardFooter({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        "flex flex-wrap items-center gap-2 border-t border-line px-5 py-4 sm:px-6",
        className,
      )}
      {...props}
    />
  );
}

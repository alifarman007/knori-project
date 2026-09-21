import Link from "next/link";

import { cn } from "@/lib/utils";

export interface WordmarkProps {
  className?: string;
  /** Renders a plain span instead of a link — for the top of an auth card. */
  asLink?: boolean;
  size?: "sm" | "md" | "lg";
}

const SIZES = { sm: "text-md", md: "text-lg", lg: "text-2xl" } as const;

/**
 * The name with the marked rule under it.
 *
 * The rule is the one idea the whole product borrows: a line drawn under words
 * that turned out to matter. It appears here, beside evidence quotes, and
 * nowhere else.
 */
export function Wordmark({ className, asLink = true, size = "md" }: WordmarkProps) {
  const content = (
    <span className="relative inline-block">
      <span className="font-serif font-medium tracking-tight text-ink">KnoRI</span>
      <span
        aria-hidden="true"
        className="absolute -bottom-0.5 left-0 h-[2px] w-full rounded-full bg-accent"
      />
    </span>
  );

  if (!asLink) {
    return <span className={cn("inline-flex", SIZES[size], className)}>{content}</span>;
  }

  return (
    <Link
      href="/"
      className={cn(
        "inline-flex rounded-sm focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-focus",
        SIZES[size],
        className,
      )}
    >
      {content}
      <span className="sr-only">KnoRI home</span>
    </Link>
  );
}

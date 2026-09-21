"use client";

import * as React from "react";

import { cn } from "@/lib/utils";

export interface TooltipProps {
  /** The explanation. Kept short; anything longer belongs on the page. */
  content: React.ReactNode;
  children: React.ReactNode;
  side?: "top" | "bottom";
  className?: string;
  /** Width of the bubble. Confidence explanations need the room. */
  width?: "sm" | "md";
}

/**
 * Hover, focus and tap all open it; Escape and blur close it. The trigger is
 * always a real button, so keyboard users reach the same text.
 */
export function Tooltip({ content, children, side = "top", width = "md", className }: TooltipProps) {
  const [open, setOpen] = React.useState(false);
  const reactId = React.useId();
  const id = `tt${reactId.replace(/:/g, "")}`;
  const timer = React.useRef<number | null>(null);

  const show = React.useCallback(() => {
    if (timer.current) window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setOpen(true), 120);
  }, []);

  const hide = React.useCallback(() => {
    if (timer.current) window.clearTimeout(timer.current);
    setOpen(false);
  }, []);

  React.useEffect(() => () => void (timer.current && window.clearTimeout(timer.current)), []);

  return (
    <span
      className={cn("relative inline-flex", className)}
      onMouseEnter={show}
      onMouseLeave={hide}
      onFocus={show}
      onBlur={hide}
      onKeyDown={(event) => {
        if (event.key === "Escape") hide();
      }}
    >
      <button
        type="button"
        aria-describedby={open ? id : undefined}
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
        className="inline-flex items-center rounded-sm focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus"
      >
        {children}
      </button>
      <span
        id={id}
        role="tooltip"
        hidden={!open}
        className={cn(
          "absolute left-1/2 z-40 -translate-x-1/2 rounded-md border border-line bg-raised px-3 py-2",
          "text-sm leading-snug text-ink-secondary shadow-float animate-fade",
          width === "sm" ? "w-44" : "w-64",
          side === "top" ? "bottom-[calc(100%+8px)]" : "top-[calc(100%+8px)]",
        )}
      >
        {content}
      </span>
    </span>
  );
}

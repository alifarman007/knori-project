import * as React from "react";

import { cn } from "@/lib/utils";

export type AlertTone = "info" | "positive" | "danger" | "accent";

const TONES: Record<AlertTone, string> = {
  info: "bg-info-soft border-info/25 text-ink",
  positive: "bg-positive-soft border-positive/25 text-ink",
  danger: "bg-danger-soft border-danger/25 text-ink",
  accent: "bg-accent-soft border-accent-line text-ink",
};

const ICON_TONES: Record<AlertTone, string> = {
  info: "text-info",
  positive: "text-positive",
  danger: "text-danger",
  accent: "text-accent",
};

const PATHS: Record<AlertTone, React.ReactNode> = {
  info: <path d="M8 7.2v4.6M8 4.6v.7" strokeLinecap="round" />,
  positive: <path d="M4.8 8.4 7 10.6l4.2-4.6" strokeLinecap="round" strokeLinejoin="round" />,
  danger: <path d="M8 4.4v4.4M8 11.1v.6" strokeLinecap="round" />,
  accent: <path d="M8 4.4v4.4M8 11.1v.6" strokeLinecap="round" />,
};

export interface AlertProps extends Omit<React.HTMLAttributes<HTMLDivElement>, "title"> {
  tone?: AlertTone;
  title?: React.ReactNode;
  /** Errors should announce themselves; informational notes should not. */
  live?: boolean;
}

export function Alert({ tone = "info", title, live, className, children, ...props }: AlertProps) {
  return (
    <div
      role={tone === "danger" || live ? "alert" : "note"}
      className={cn("flex gap-3 rounded-md border px-4 py-3", TONES[tone], className)}
      {...props}
    >
      <svg
        viewBox="0 0 16 16"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.5"
        aria-hidden="true"
        className={cn("mt-0.5 size-4 shrink-0", ICON_TONES[tone])}
      >
        <circle cx="8" cy="8" r="6.6" />
        {PATHS[tone]}
      </svg>
      <div className="min-w-0 flex-1 text-sm">
        {title ? <p className="font-medium text-ink">{title}</p> : null}
        {children ? <div className={cn("text-ink-secondary", title && "mt-1")}>{children}</div> : null}
      </div>
    </div>
  );
}
